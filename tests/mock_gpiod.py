#!/usr/bin/env python3
"""
Mock implementation of libgpiod v2 for testing without hardware.
Simulates GPIO chip, line settings, and edge events with nanosecond-precision timestamps.
"""

import time
import threading
import queue
from typing import Optional, Dict, List
from dataclasses import dataclass


# Mock enums matching libgpiod v2 API
class Direction:
    INPUT = "input"
    OUTPUT = "output"


class Edge:
    NONE = "none"
    RISING = "rising"
    FALLING = "falling"
    BOTH = "both"


class Bias:
    AS_IS = "as-is"
    DISABLE = "disable"
    PULL_UP = "pull-up"
    PULL_DOWN = "pull-down"


@dataclass
class MockLineInfo:
    """Mock line info returned by get_line_info()."""
    consumer: str = ""
    direction: str = Direction.INPUT
    edge_detection: str = Edge.NONE
    bias: str = Bias.AS_IS


@dataclass
class MockEdgeEvent:
    """Mock edge event with timestamp and line offset."""
    line_offset: int
    timestamp_ns: int
    event_type: str = Edge.RISING  # For compatibility


class MockLineSettings:
    """Mock line settings matching libgpiod.LineSettings."""
    
    def __init__(self):
        self.direction = Direction.INPUT
        self.edge_detection = Edge.RISING
        self.bias = Bias.PULL_UP
        self.debounce_period_us = 0


class MockRequest:
    """Mock request object that manages edge event queue."""
    
    def __init__(self, chip: 'MockChip', consumer: str, config: Dict[int, MockLineSettings]):
        self.chip = chip
        self.consumer = consumer
        self.config = config  # pin -> settings mapping
        self._event_queue = queue.Queue()
        self._closed = False
        self._lock = threading.Lock()
        
        # Register this request with the chip
        self.chip._register_request(self, config)
    
    def wait_edge_events(self, timeout: float = 0.5) -> bool:
        """
        Wait for edge events to be available.
        Returns True if events are ready, False on timeout.
        """
        if self._closed:
            return False
        
        try:
            # Check if events are available (non-blocking)
            if not self._event_queue.empty():
                return True
            
            # Wait for events with timeout
            start_time = time.perf_counter()
            while time.perf_counter() - start_time < timeout:
                if not self._event_queue.empty():
                    return True
                time.sleep(0.001)  # Small sleep to avoid busy-waiting
            
            return False
        except Exception:
            return False
    
    def read_edge_events(self) -> List[MockEdgeEvent]:
        """
        Read available edge events from the queue.
        Returns list of MockEdgeEvent objects.
        """
        if self._closed:
            return []
        
        events = []
        try:
            # Read all available events (non-blocking)
            while not self._event_queue.empty():
                try:
                    event = self._event_queue.get_nowait()
                    events.append(event)
                except queue.Empty:
                    break
        except Exception:
            pass
        
        return events
    
    def release(self):
        """Release the request and cleanup."""
        with self._lock:
            if not self._closed:
                self._closed = True
                self.chip._unregister_request(self)
                # Clear any remaining events
                while not self._event_queue.empty():
                    try:
                        self._event_queue.get_nowait()
                    except queue.Empty:
                        break
    
    def inject_event(self, event: MockEdgeEvent):
        """Inject an event into the queue (for testing)."""
        if not self._closed:
            self._event_queue.put(event)


class MockChip:
    """Mock GPIO chip simulating /dev/gpiochip0."""
    
    def __init__(self, chip_name: str = "/dev/gpiochip0"):
        self.chip_name = chip_name
        self._line_info: Dict[int, MockLineInfo] = {}
        self._requests: List[MockRequest] = []
        self._lock = threading.Lock()
    
    def get_line_info(self, offset: int) -> MockLineInfo:
        """Get line information for a GPIO pin."""
        if offset not in self._line_info:
            # Default line info
            self._line_info[offset] = MockLineInfo(
                consumer="",
                direction=Direction.INPUT,
                edge_detection=Edge.NONE,
                bias=Bias.AS_IS
            )
        return self._line_info[offset]
    
    def request_lines(self, consumer: str, config: Dict[int, MockLineSettings]) -> MockRequest:
        """
        Request GPIO lines with specified settings.
        Returns MockRequest object.
        """
        request = MockRequest(self, consumer, config)
        return request
    
    def close(self):
        """Close the chip and cleanup."""
        with self._lock:
            # Release all requests
            for request in list(self._requests):
                request.release()
            self._requests.clear()
            self._line_info.clear()
    
    def _register_request(self, request: MockRequest, config: Dict[int, MockLineSettings]):
        """Register a request with this chip (internal)."""
        with self._lock:
            self._requests.append(request)
            # Update line info based on config
            for offset, settings in config.items():
                self._line_info[offset] = MockLineInfo(
                    consumer=request.consumer,
                    direction=settings.direction,
                    edge_detection=settings.edge_detection,
                    bias=settings.bias
                )
    
    def _unregister_request(self, request: MockRequest):
        """Unregister a request from this chip (internal)."""
        with self._lock:
            if request in self._requests:
                self._requests.remove(request)
    
    def inject_event_to_all_requests(self, event: MockEdgeEvent):
        """Inject an event to all registered requests for the specified pin."""
        with self._lock:
            for request in self._requests:
                # Only inject if the request is configured for this pin
                if event.line_offset in request.config:
                    request.inject_event(event)


# Create a module-level mock gpiod object
class MockGpiodModule:
    """Mock gpiod module that provides the same API as real libgpiod."""
    
    Chip = MockChip
    LineSettings = MockLineSettings
    
    class line:
        """Mock line submodule with enums."""
        Direction = Direction
        Edge = Edge
        Bias = Bias


# Global instance for monkey-patching
mock_gpiod = MockGpiodModule()
