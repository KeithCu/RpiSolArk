/*
 * High-performance pulse counter for RPi4 GPIO interrupts.
 * Avoids Python GIL issues by using C-level counting.
 * 
 * Compile with: gcc -shared -fPIC -o pulse_counter.so pulse_counter.c
 */

#include <Python.h>
#include <stdint.h>
#include <time.h>

// Global counters for each GPIO pin (max 4 pins)
static volatile uint64_t pulse_counts[4] = {0};
static volatile int pin_mapping[4] = {-1, -1, -1, -1};
static int counter_initialized = 0;

// Initialize the counter system
static int init_counters() {
    if (counter_initialized) return 1;
    
    // Initialize all counters to zero
    for (int i = 0; i < 4; i++) {
        pulse_counts[i] = 0;
        pin_mapping[i] = -1;
    }
    
    counter_initialized = 1;
    return 1;
}

// Register a GPIO pin for counting
static int register_pin(int pin) {
    if (!init_counters()) return 0;
    
    // Find available slot
    for (int i = 0; i < 4; i++) {
        if (pin_mapping[i] == -1) {
            pin_mapping[i] = pin;
            pulse_counts[i] = 0;
            return i;
        }
    }
    
    return -1; // No available slots
}

// Get current count for a pin
static uint64_t get_count(int pin) {
    if (!counter_initialized) return 0;
    
    for (int i = 0; i < 4; i++) {
        if (pin_mapping[i] == pin) {
            return pulse_counts[i];
        }
    }
    
    return 0;
}

// Reset count for a pin
static void reset_count(int pin) {
    if (!counter_initialized) return;
    
    for (int i = 0; i < 4; i++) {
        if (pin_mapping[i] == pin) {
            pulse_counts[i] = 0;
            break;
        }
    }
}

// Increment count for a pin (called from interrupt)
static void increment_count(int pin) {
    if (!counter_initialized) return;
    
    // Fast path - no mutex needed for increment
    for (int i = 0; i < 4; i++) {
        if (pin_mapping[i] == pin) {
            pulse_counts[i]++;
            return;
        }
    }
}

// Python interface functions
static PyObject* py_register_pin(PyObject* self, PyObject* args) {
    int pin;
    if (!PyArg_ParseTuple(args, "i", &pin)) {
        return NULL;
    }
    
    int slot = register_pin(pin);
    if (slot == -1) {
        PyErr_SetString(PyExc_RuntimeError, "No available counter slots");
        return NULL;
    }
    
    return PyLong_FromLong(slot);
}

static PyObject* py_get_count(PyObject* self, PyObject* args) {
    int pin;
    if (!PyArg_ParseTuple(args, "i", &pin)) {
        return NULL;
    }
    
    uint64_t count = get_count(pin);
    return PyLong_FromUnsignedLongLong(count);
}

static PyObject* py_reset_count(PyObject* self, PyObject* args) {
    int pin;
    if (!PyArg_ParseTuple(args, "i", &pin)) {
        return NULL;
    }
    
    reset_count(pin);
    Py_RETURN_NONE;
}

static PyObject* py_increment_count(PyObject* self, PyObject* args) {
    int pin;
    if (!PyArg_ParseTuple(args, "i", &pin)) {
        return NULL;
    }
    
    increment_count(pin);
    Py_RETURN_NONE;
}

// Method definitions
static PyMethodDef PulseCounterMethods[] = {
    {"register_pin", py_register_pin, METH_VARARGS, "Register a GPIO pin for counting"},
    {"get_count", py_get_count, METH_VARARGS, "Get current pulse count for a pin"},
    {"reset_count", py_reset_count, METH_VARARGS, "Reset pulse count for a pin"},
    {"increment_count", py_increment_count, METH_VARARGS, "Increment pulse count for a pin"},
    {NULL, NULL, 0, NULL}
};

// Module definition
static struct PyModuleDef pulse_counter_module = {
    PyModuleDef_HEAD_INIT,
    "pulse_counter",
    "High-performance pulse counter for GPIO interrupts",
    -1,
    PulseCounterMethods
};

PyMODINIT_FUNC PyInit_pulse_counter(void) {
    return PyModule_Create(&pulse_counter_module);
}
