#!/usr/bin/env python3
"""
Pure-Python GPIO pulse counter using libgpiod v2.
Kernel handles IRQs and queues edge events; a Python thread drains them.
Suitable for ≤ two pins at modest rates (e.g., ≤240 Hz per pin).
"""

import os
import sys
import time
import logging
import threading
import datetime
from typing import Optional, Dict, Tuple

import gpiod  # libgpiod v2 Python bindings

# Module-specific log level override (empty string or None to use default from config.yaml)
MODULE_LOG_LEVEL = None  # Use default log level from config.yaml


class GPIOEventCounter:
	"""Pure-Python counter backend using libgpiod v2 edge events."""

	def __init__(self, logger: logging.Logger, chip_name: str = "/dev/gpiochip0"):
		self.logger = logger
		
		# Apply module-specific log level if set
		if MODULE_LOG_LEVEL and MODULE_LOG_LEVEL.strip():
			try:
				log_level = getattr(logging, MODULE_LOG_LEVEL.strip().upper())
				self.logger.setLevel(log_level)
			except AttributeError:
				self.logger.warning(f"Invalid MODULE_LOG_LEVEL '{MODULE_LOG_LEVEL}', using default")
		
		self.chip_name = chip_name
		self.registered_pins: Dict[int, int] = {}  # pin -> index (0..1)
		self.counts: Dict[int, int] = {}
		self.timestamps: Dict[int, list] = {}  # pin -> list of timestamps (ns)
		self.last_valid_timestamp: Dict[int, int] = {} # pin -> last valid timestamp (ns)
		self.debounce_ns = 200000  # 0.2ms default debounce (reject < 0.2ms intervals)
		self._counts_lock = threading.Lock()
		self._chip: Optional[gpiod.Chip] = None
		self._request: Optional[gpiod.Request] = None
		self._thread: Optional[threading.Thread] = None
		self._running = False
		# Debug tracking
		self._reset_count_calls = 0
		self._last_reset_time: Optional[float] = None
		# Event statistics tracking per pin
		self._events_received: Dict[int, int] = {}  # pin -> total events from hardware
		self._events_debounced: Dict[int, int] = {}  # pin -> events rejected by debounce
		self._events_accepted: Dict[int, int] = {}  # pin -> events accepted
		self._interval_stats: Dict[int, list] = {}  # pin -> list of intervals (ns) for statistics
		self.logger.info("Using pure-Python libgpiod v2 counter backend")

	def _start_request(self):
		offsets = list(self.registered_pins.keys())
		if not offsets:
			raise RuntimeError("No pins registered")
		request_start = time.perf_counter()
		self.logger.info(f"[REQUEST_CREATE] Starting for pins: {offsets}, chip={self.chip_name}, time={request_start:.3f}")
		self._chip = gpiod.Chip(self.chip_name)

		# Log current line state before requesting
		for offset in offsets:
			try:
				line_info = self._chip.get_line_info(offset)
				self.logger.info(f"[REQUEST_CREATE] GPIO {offset} current state: consumer='{line_info.consumer}', direction={line_info.direction}, edge_detection={line_info.edge_detection}, bias={line_info.bias}")
			except Exception as e:
				self.logger.warning(f"[REQUEST_CREATE] Could not get line info for GPIO {offset}: {e}")

		settings = gpiod.LineSettings()
		settings.direction = gpiod.line.Direction.INPUT
		settings.edge_detection = gpiod.line.Edge.RISING  # Count only rising edges (fixes double-counting issue)
		# Enable internal pull-up for optocoupler (H11AA1 needs pull-up)
		settings.bias = gpiod.line.Bias.PULL_UP
		# Note: Hardware debounce causes issues with libgpiod v2, using software debounce only
		self.logger.debug(f"[REQUEST_CREATE] Using software debounce only (hardware debounce disabled)")

		self.logger.info(f"[REQUEST_CREATE] Settings: direction={settings.direction}, edge_detection={settings.edge_detection}, bias={settings.bias}")

		# Create config dictionary mapping offsets to settings
		config = {offset: settings for offset in offsets}
		self._request = self._chip.request_lines(consumer="pulse_counter_py", config=config)
		request_duration = (time.perf_counter() - request_start) * 1000
		self.logger.info(f"[REQUEST_CREATE] Completed for pins: {offsets}, took {request_duration:.1f}ms, request={self._request}")

	def _start_thread(self):
		self._running = True
		self._thread = threading.Thread(target=self._event_loop, name="gpiod-events", daemon=True)
		thread_start_time = time.perf_counter()
		self._thread.start()
		self.logger.info(f"[THREAD_START] Event loop thread started, name={self._thread.name}, id={self._thread.ident}, time={thread_start_time:.3f}")

	def _stop_thread(self):
		if not self._running:
			self.logger.debug(f"[THREAD_STOP] Thread not running, nothing to stop")
			return
		stop_start = time.perf_counter()
		thread_name = self._thread.name if self._thread else "None"
		thread_id = self._thread.ident if self._thread else "None"
		self.logger.info(f"[THREAD_STOP] Stopping event loop thread, name={thread_name}, id={thread_id}")
		self._running = False
		if self._thread is not None:
			self._thread.join(timeout=2.0)
			join_success = not self._thread.is_alive()
			stop_duration = (time.perf_counter() - stop_start) * 1000
			self.logger.info(f"[THREAD_STOP] Thread join completed, success={join_success}, took {stop_duration:.1f}ms")
			self._thread = None

	def _close_request(self):
		close_start = time.perf_counter()
		had_request = self._request is not None
		had_chip = self._chip is not None
		self.logger.info(f"[REQUEST_CLOSE] Closing request={had_request}, chip={had_chip}")
		if self._request is not None:
			try:
				self._request.release()
				self.logger.debug(f"[REQUEST_CLOSE] Request released successfully")
			except Exception as e:
				self.logger.warning(f"[REQUEST_CLOSE] Request release failed: {e}")
			self._request = None
		if self._chip is not None:
			try:
				self._chip.close()
				self.logger.debug(f"[REQUEST_CLOSE] Chip closed successfully")
			except Exception as e:
				self.logger.warning(f"[REQUEST_CLOSE] Chip close failed: {e}")
			self._chip = None
		close_duration = (time.perf_counter() - close_start) * 1000
		self.logger.info(f"[REQUEST_CLOSE] Completed in {close_duration:.1f}ms")

	def _reconfigure(self):
		# Stop, rebuild, and restart with current pins
		reconfig_start = time.perf_counter()
		pins = list(self.registered_pins.keys())
		self.logger.info(f"[RECONFIGURE] Starting reconfiguration for pins: {pins}")
		self._stop_thread()
		self._close_request()
		self._start_request()
		self._start_thread()
		reconfig_duration = (time.perf_counter() - reconfig_start) * 1000
		self.logger.info(f"[RECONFIGURE] Completed in {reconfig_duration:.1f}ms")

	def register_pin(self, pin: int, debounce_ns: int = 2000000) -> bool:
		"""Register a GPIO pin for counting (BCM offset)."""
		register_start = time.perf_counter()
		self.logger.info(f"[PIN_REGISTER] Registering pin {pin}, debounce_ns={debounce_ns}, already_running={self._running}")
		if pin in self.registered_pins:
			self.logger.info(f"[PIN_REGISTER] Pin {pin} already registered, skipping")
			return True
		if len(self.registered_pins) >= 2:
			self.logger.error("[PIN_REGISTER] Only two concurrent pins are supported")
			return False
		self.registered_pins[pin] = len(self.registered_pins)
		self.debounce_ns = debounce_ns
		with self._counts_lock:
			self.counts.setdefault(pin, 0)
			self.timestamps.setdefault(pin, [])
			self.last_valid_timestamp.setdefault(pin, 0)
			self._events_received.setdefault(pin, 0)
			self._events_debounced.setdefault(pin, 0)
			self._events_accepted.setdefault(pin, 0)
			self._interval_stats.setdefault(pin, [])
		# If already running, reconfigure to include the new pin
		if self._running:
			self.logger.info(f"[PIN_REGISTER] Request already running, will reconfigure")
			try:
				self._reconfigure()
			except Exception as e:
				self.logger.error(f"[PIN_REGISTER] Failed to reconfigure request for new pin: {e}")
				return False
		else:
			# Lazy start: build request and start thread now
			self.logger.info(f"[PIN_REGISTER] No existing request, creating new one")
			try:
				self._start_request()
				self._start_thread()
			except Exception as e:
				self.logger.error(f"[PIN_REGISTER] Failed to start event handling: {e}")
				self._close_request()
				return False
		register_duration = (time.perf_counter() - register_start) * 1000
		self.logger.info(f"[PIN_REGISTER] Pin {pin} registered successfully in {register_duration:.1f}ms")
		return True

	def _event_loop(self):
		assert self._request is not None
		loop_start_time = time.perf_counter()
		self.logger.info(f"[EVENT_LOOP] Started at {loop_start_time:.3f}, thread={threading.current_thread().name}")
		event_count = 0
		wait_count = 0
		timeout_count = 0
		last_rate_log_time = time.perf_counter()
		last_rate_event_count = 0
		last_event_time_ns = 0  # Track time between events for gap detection

		while self._running:
			try:
				wait_count += 1
				wait_start = time.perf_counter()
				ready = self._request.wait_edge_events(timeout=0.5)
				wait_duration = (time.perf_counter() - wait_start) * 1000

				if not ready:
					timeout_count += 1
					# Log only first few timeouts, then every 100th to reduce CPU overhead
					if timeout_count <= 3 or timeout_count % 100 == 0:
						self.logger.debug(f"[EVENT_WAIT] timeout after {wait_duration:.1f}ms (timeout #{timeout_count}, total waits={wait_count})")
					continue

				# Events are ready - read them
				read_start = time.perf_counter()
				events = self._request.read_edge_events()
				read_duration = (time.perf_counter() - read_start) * 1000

				if not events:
					self.logger.warning(f"[EVENT_READ] wait returned ready but read returned empty! wait_duration={wait_duration:.1f}ms")
					continue

				# Only log event reads occasionally to reduce CPU overhead (every 1000 events or if read takes >10ms)
				if event_count % 1000 == 0 or read_duration > 10.0:
					self.logger.debug(f"[EVENT_READ] got {len(events)} events, wait={wait_duration:.1f}ms, read={read_duration:.2f}ms")
				
				with self._counts_lock:
					for ev in events:
						pin = ev.line_offset
						current_ts = ev.timestamp_ns
						
						# Track total events received from hardware
						self._events_received[pin] = self._events_received.get(pin, 0) + 1
						
						# Calculate interval since last event (for gap detection)
						if last_event_time_ns > 0:
							interval_ms = (current_ts - last_event_time_ns) / 1e6
							if interval_ms > 100:  # Gap > 100ms
								self.logger.warning(f"[EVENT_GAP] Large gap: {interval_ms:.1f}ms since last event (pin={pin}, count={event_count})")
						
						# Software filtering / Debounce
						# Reject if interval < debounce_ns (e.g. 0.2ms)
						last_ts = self.last_valid_timestamp.get(pin, 0)
						if last_ts > 0 and (current_ts - last_ts) < self.debounce_ns:
							# Noise detected, skip this event
							interval_us = (current_ts - last_ts) / 1000
							self._events_debounced[pin] = self._events_debounced.get(pin, 0) + 1
							if event_count < 20:  # Log first debounced events
								self.logger.debug(f"[EVENT_DEBOUNCE] Rejected event on pin {pin}, interval={interval_us:.1f}us < {self.debounce_ns/1000:.1f}us")
							continue
						
						# Valid event - update last event time for gap detection
						last_event_time_ns = current_ts
						
						# Track accepted events
						self._events_accepted[pin] = self._events_accepted.get(pin, 0) + 1
						
						# Calculate and store interval for statistics
						if last_ts > 0:
							interval_ns = current_ts - last_ts
							self._interval_stats[pin].append(interval_ns)
						
						# Valid event
						self.counts[pin] = self.counts.get(pin, 0) + 1
						self.last_valid_timestamp[pin] = current_ts
						
						# Store timestamp (ns)
						if pin in self.timestamps:
							self.timestamps[pin].append(current_ts)
							# Only log first event timestamp to reduce CPU overhead
							if event_count == 1:
								self.logger.debug(f"[EVENT] Stored first timestamp for pin {pin}: {current_ts}")
						else:
							self.logger.warning(f"[EVENT] Pin {pin} not in timestamps dict! Keys: {list(self.timestamps.keys())}")
							
						event_count += 1
						
						# Log first 10 events with timing details
						if event_count <= 10:
							if last_ts > 0:
								interval_ms = (current_ts - last_ts) / 1e6
								self.logger.info(f"[EVENT] #{event_count} pin={pin} count={self.counts[pin]} interval={interval_ms:.2f}ms")
							else:
								self.logger.info(f"[EVENT] #{event_count} pin={pin} count={self.counts[pin]} (first event)")
				
				# Log event rate periodically (every 1 second or 500 events)
				now = time.perf_counter()
				time_since_rate_log = now - last_rate_log_time
				events_since_rate_log = event_count - last_rate_event_count
				if time_since_rate_log >= 1.0 or events_since_rate_log >= 500:
					rate = events_since_rate_log / time_since_rate_log if time_since_rate_log > 0 else 0
					self.logger.info(f"[EVENT_RATE] {events_since_rate_log} events in {time_since_rate_log:.2f}s = {rate:.1f}/s (total={event_count}, expect ~120/s)")
					last_rate_log_time = now
					last_rate_event_count = event_count
					
			except Exception as e:
				# Transient read/wait errors; keep running
				self.logger.warning(f"[EVENT_LOOP] Error: {e}", exc_info=True)
				time.sleep(0.01)
		
		# Log when loop exits
		loop_duration = time.perf_counter() - loop_start_time
		self.logger.info(f"[EVENT_LOOP] Exiting after {loop_duration:.1f}s, total_events={event_count}, waits={wait_count}, timeouts={timeout_count}")

	def get_count(self, pin: int) -> int:
		with self._counts_lock:
			count = int(self.counts.get(pin, 0))
			self.logger.debug(f"[GET_COUNT] pin={pin} count={count} thread={threading.current_thread().name}")
			return count

	def get_timestamps(self, pin: int) -> list:
		"""Get list of timestamps (ns) for the pin."""
		with self._counts_lock:
			timestamps = list(self.timestamps.get(pin, []))
			self.logger.debug(f"[GET_TIMESTAMPS] pin={pin} count={len(timestamps)} thread={threading.current_thread().name}")
			return timestamps
	
	def get_frequency_info(self, pin: int) -> Tuple[int, int, int]:
		"""
		Get frequency statistics without copying the full timestamp list.
		Returns: (count, first_timestamp_ns, last_timestamp_ns)
		"""
		with self._counts_lock:
			ts_list = self.timestamps.get(pin, [])
			count = len(ts_list)
			if count > 0:
				first_ts = ts_list[0]
				last_ts = ts_list[-1]
				duration_ms = (last_ts - first_ts) / 1e6
				self.logger.debug(f"[GET_FREQ_INFO] pin={pin} count={count} duration={duration_ms:.1f}ms")
				return (count, first_ts, last_ts)
			else:
				self.logger.debug(f"[GET_FREQ_INFO] pin={pin} count=0 (no timestamps)")
				return (0, 0, 0)

	def reset_count(self, pin: int) -> bool:
		# Track lock acquisition time
		lock_start = time.perf_counter()
		with self._counts_lock:
			lock_duration = (time.perf_counter() - lock_start) * 1000
			if lock_duration > 1.0:  # Warn if >1ms
				self.logger.warning(f"[RESET] Lock acquisition took {lock_duration:.2f}ms - possible contention")
			
			if pin in self.counts:
				# Capture state before reset
				count_before = self.counts[pin]
				timestamps_before = len(self.timestamps.get(pin, []))
				
				self.counts[pin] = 0
				self.timestamps[pin] = []
				self.last_valid_timestamp[pin] = 0
				
				# Track reset calls
				self._reset_count_calls += 1
				now = time.time()
				perf_now = time.perf_counter()
				thread_name = threading.current_thread().name
				if self._last_reset_time:
					interval = now - self._last_reset_time
					self.logger.info(f"[RESET] #{self._reset_count_calls} pin={pin} count_before={count_before} timestamps_before={timestamps_before} interval={interval:.3f}s thread={thread_name} perf_time={perf_now:.3f}")
				else:
					self.logger.info(f"[RESET] #{self._reset_count_calls} pin={pin} count_before={count_before} timestamps_before={timestamps_before} (first reset) thread={thread_name} perf_time={perf_now:.3f}")
				self._last_reset_time = now
				
				return True
			self.logger.warning(f"[RESET] Pin {pin} not found in counts dict! Available: {list(self.counts.keys())}")
			return False

	def setup_gpio_interrupt(self, pin: int) -> bool:
		"""Register pin for edge handling in pure Python."""
		return self.register_pin(pin)

	def start(self) -> bool:
		# Kept for API compatibility; already started lazily on register
		return True

	def stop(self):
		self._stop_thread()
		self._close_request()
	
	def check_interrupts(self):
		"""Compatibility no-op (events handled in background)."""
		return None

	def poll_events_once(self, timeout: float = 0.5) -> int:
		"""
		Poll for events once (for testing without background thread).
		Returns the number of events processed.
		"""
		if not self._request:
			self.logger.warning("[POLL] No request available")
			return 0

		try:
			ready = self._request.wait_edge_events(timeout=timeout)
			if not ready:
				self.logger.debug(f"[POLL] No events ready (timeout={timeout}s)")
				return 0

			events = self._request.read_edge_events()
			if not events:
				self.logger.warning("[POLL] Wait returned ready but read returned empty")
				return 0

			self.logger.info(f"[POLL] Processing {len(events)} events")

			with self._counts_lock:
				for ev in events:
					pin = ev.line_offset
					current_ts = ev.timestamp_ns

					# Software filtering / Debounce
					last_ts = self.last_valid_timestamp.get(pin, 0)
					if last_ts > 0 and (current_ts - last_ts) < self.debounce_ns:
						continue

					# Valid event
					self.counts[pin] = self.counts.get(pin, 0) + 1
					self.last_valid_timestamp[pin] = current_ts

					# Store timestamp
					if pin in self.timestamps:
						self.timestamps[pin].append(current_ts)

			return len(events)

		except Exception as e:
			self.logger.error(f"[POLL] Error polling events: {e}")
			return 0
	
	def get_event_statistics(self, pin: int, include_intervals: bool = False) -> Dict[str, any]:
		"""
		Get event statistics for a pin including received, debounced, accepted counts
		and optionally interval statistics (min, max, mean, std dev, median).
		
		Args:
			pin: GPIO pin number
			include_intervals: If True, calculate expensive interval statistics (default: False for performance)
		
		Returns:
			Dictionary with statistics or None if pin not found
		"""
		with self._counts_lock:
			if pin not in self.counts:
				return None
			
			received = self._events_received.get(pin, 0)
			debounced = self._events_debounced.get(pin, 0)
			accepted = self._events_accepted.get(pin, 0)
			
			stats = {
				'received': received,
				'debounced': debounced,
				'accepted': accepted,
				'count': self.counts.get(pin, 0),
				'timestamp_count': len(self.timestamps.get(pin, [])),
			}
			
			# Only calculate expensive interval statistics if explicitly requested
			# This avoids O(n log n) sorting and multiple list passes on every measurement
			if include_intervals:
				intervals_ns = self._interval_stats.get(pin, [])
				if len(intervals_ns) > 0:
					intervals_us = [i / 1000.0 for i in intervals_ns]
					intervals_ms = [i / 1000000.0 for i in intervals_ns]
					stats['intervals'] = {
						'count': len(intervals_ns),
						'min_us': min(intervals_us),
						'max_us': max(intervals_us),
						'mean_us': sum(intervals_us) / len(intervals_us),
						'min_ms': min(intervals_ms),
						'max_ms': max(intervals_ms),
						'mean_ms': sum(intervals_ms) / len(intervals_ms),
					}
					
					# Calculate std dev
					mean_us = stats['intervals']['mean_us']
					variance = sum((x - mean_us) ** 2 for x in intervals_us) / len(intervals_us)
					stats['intervals']['std_dev_us'] = variance ** 0.5
					stats['intervals']['std_dev_ms'] = stats['intervals']['std_dev_us'] / 1000.0
					
					# Calculate median (expensive - requires sorting)
					sorted_intervals_us = sorted(intervals_us)
					mid = len(sorted_intervals_us) // 2
					if len(sorted_intervals_us) % 2 == 0:
						stats['intervals']['median_us'] = (sorted_intervals_us[mid - 1] + sorted_intervals_us[mid]) / 2.0
					else:
						stats['intervals']['median_us'] = sorted_intervals_us[mid]
					stats['intervals']['median_ms'] = stats['intervals']['median_us'] / 1000.0
				else:
					stats['intervals'] = None
			else:
				stats['intervals'] = None
			
			return stats
	
	def cleanup(self):
		try:
			self.stop()
		finally:
			with self._counts_lock:
				self.counts.clear()
				self.timestamps.clear()
				self._events_received.clear()
				self._events_debounced.clear()
				self._events_accepted.clear()
				self._interval_stats.clear()
			self.registered_pins.clear()


def create_counter(logger: logging.Logger):
	"""Create the pure-Python libgpiod v2 counter implementation."""
	logger.info("Using pure-Python libgpiod v2 counter implementation")
	return GPIOEventCounter(logger)
