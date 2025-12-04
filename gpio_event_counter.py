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
from typing import Optional, Dict

import gpiod  # libgpiod v2 Python bindings

class GPIOEventCounter:
	"""Pure-Python counter backend using libgpiod v2 edge events."""

	def __init__(self, logger: logging.Logger, chip_name: str = "/dev/gpiochip0"):
		self.logger = logger
		self.chip_name = chip_name
		self.registered_pins: Dict[int, int] = {}  # pin -> index (0..1)
		self.counts: Dict[int, int] = {}
		self._counts_lock = threading.Lock()
		self._chip: Optional[gpiod.Chip] = None
		self._request: Optional[gpiod.Request] = None
		self._thread: Optional[threading.Thread] = None
		self._running = False
		self.logger.info("Using pure-Python libgpiod v2 counter backend")

	def _start_request(self):
		offsets = list(self.registered_pins.keys())
		if not offsets:
			raise RuntimeError("No pins registered")
		self._chip = gpiod.Chip(self.chip_name)
		settings = gpiod.LineSettings()
		settings.direction = gpiod.line.Direction.INPUT
		settings.edge_detection = gpiod.line.Edge.BOTH  # Count both rising and falling edges
		# Enable internal pull-up for optocoupler (H11AA1 needs pull-up)
		settings.bias = gpiod.line.Bias.PULL_UP
		
		# Create config dictionary mapping offsets to settings
		config = {offset: settings for offset in offsets}
		self._request = self._chip.request_lines(consumer="pulse_counter_py", config=config)

	def _start_thread(self):
		self._running = True
		self._thread = threading.Thread(target=self._event_loop, name="gpiod-events", daemon=True)
		self._thread.start()

	def _stop_thread(self):
		if not self._running:
			return
		self._running = False
		if self._thread is not None:
			self._thread.join(timeout=2.0)
			self._thread = None

	def _close_request(self):
		if self._request is not None:
			try:
				self._request.release()
			except Exception:
				pass
			self._request = None
		if self._chip is not None:
			try:
				self._chip.close()
			except Exception:
				pass
			self._chip = None

	def _reconfigure(self):
		# Stop, rebuild, and restart with current pins
		self._stop_thread()
		self._close_request()
		self._start_request()
		self._start_thread()

	def register_pin(self, pin: int) -> bool:
		"""Register a GPIO pin for counting (BCM offset)."""
		if pin in self.registered_pins:
			return True
		if len(self.registered_pins) >= 2:
			self.logger.error("Only two concurrent pins are supported")
			return False
		self.registered_pins[pin] = len(self.registered_pins)
		with self._counts_lock:
			self.counts.setdefault(pin, 0)
		# If already running, reconfigure to include the new pin
		if self._running:
			try:
				self._reconfigure()
			except Exception as e:
				self.logger.error(f"Failed to reconfigure request for new pin: {e}")
				return False
		else:
			# Lazy start: build request and start thread now
			try:
				self._start_request()
				self._start_thread()
			except Exception as e:
				self.logger.error(f"Failed to start event handling: {e}")
				self._close_request()
				return False
		return True

	def _event_loop(self):
		assert self._request is not None
		self.logger.debug("Event loop started")
		event_count = 0
		while self._running:
			try:
				ready = self._request.wait_edge_events(timeout=0.5)
				if not ready:
					continue
				events = self._request.read_edge_events()
				if not events:
					continue
				with self._counts_lock:
					for ev in events:
						pin = ev.line_offset
						self.counts[pin] = self.counts.get(pin, 0) + 1
						event_count += 1
						if event_count <= 10:  # Log first 10 events
							self.logger.debug(f"Event detected on pin {pin}, count={self.counts[pin]}")
			except Exception as e:
				# Transient read/wait errors; keep running
				self.logger.warning(f"Event loop error: {e}", exc_info=True)
				time.sleep(0.01)

	def get_count(self, pin: int) -> int:
		with self._counts_lock:
			return int(self.counts.get(pin, 0))

	def reset_count(self, pin: int) -> bool:
		with self._counts_lock:
			if pin in self.counts:
				self.counts[pin] = 0
				return True
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
	
	def cleanup(self):
		try:
			self.stop()
		finally:
			with self._counts_lock:
				self.counts.clear()
			self.registered_pins.clear()


def create_counter(logger: logging.Logger):
	"""Create the pure-Python libgpiod v2 counter implementation."""
	logger.info("Using pure-Python libgpiod v2 counter implementation")
	return GPIOEventCounter(logger)
