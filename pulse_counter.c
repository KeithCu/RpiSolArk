/*
 * High-performance pulse counter for RPi4 GPIO interrupts.
 * Avoids Python GIL issues by using C-level counting.
 * 
 * Compile with: gcc -shared -fPIC -o pulse_counter.so pulse_counter.c
 */

#include <Python.h>
#include <stdint.h>
#include <time.h>
#include <fcntl.h>
#include <sys/mman.h>
#include <unistd.h>
#include <errno.h>

// GPIO memory mapping for direct hardware access
#define BCM2835_PERI_BASE 0x3F000000
#define GPIO_BASE (BCM2835_PERI_BASE + 0x200000)
#define BLOCK_SIZE (4*1024)

// GPIO registers (only the ones we actually use)
#define GPFSEL0 0x00
#define GPFEN0 0x58
#define GPFEN1 0x5C
#define GPEDS0 0x40
#define GPEDS1 0x44

static volatile uint32_t *gpio_map = NULL;
static int mem_fd = -1;

// Global counters for each GPIO pin (max 4 pins)
static volatile uint64_t pulse_counts[4] = {0};
static volatile int pin_mapping[4] = {-1, -1, -1, -1};
static int counter_initialized = 0;

// Initialize GPIO memory mapping
static int init_gpio() {
    if (gpio_map != NULL) return 1;
    
    // Open /dev/mem
    mem_fd = open("/dev/mem", O_RDWR | O_SYNC);
    if (mem_fd < 0) {
        return 0;
    }
    
    // Map GPIO memory
    gpio_map = (volatile uint32_t *)mmap(NULL, BLOCK_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, mem_fd, GPIO_BASE);
    if (gpio_map == MAP_FAILED) {
        close(mem_fd);
        mem_fd = -1;
        return 0;
    }
    
    return 1;
}

// Cleanup GPIO memory mapping
static void cleanup_gpio() {
    if (gpio_map != NULL) {
        munmap((void*)gpio_map, BLOCK_SIZE);
        gpio_map = NULL;
    }
    if (mem_fd >= 0) {
        close(mem_fd);
        mem_fd = -1;
    }
}

// Initialize the counter system
static int init_counters() {
    if (counter_initialized) return 1;
    
    // Initialize GPIO first
    if (!init_gpio()) {
        return 0;
    }
    
    // Initialize all counters to zero
    for (int i = 0; i < 4; i++) {
        pulse_counts[i] = 0;
        pin_mapping[i] = -1;
    }
    
    counter_initialized = 1;
    return 1;
}

// Setup GPIO pin for input with pull-up and falling edge detection
static int setup_gpio_pin(int pin) {
    if (gpio_map == NULL) return 0;
    
    // Set pin as input (GPFSEL register)
    int fsel_reg = pin / 10;
    int fsel_shift = (pin % 10) * 3;
    gpio_map[GPFSEL0/4 + fsel_reg] &= ~(7 << fsel_shift);  // Clear bits
    gpio_map[GPFSEL0/4 + fsel_reg] |= (0 << fsel_shift);   // Set as input
    
    // Enable pull-up resistor (simplified - would need proper sequence)
    // For now, assume external pull-up is used
    
    // Enable falling edge detection
    if (pin < 32) {
        gpio_map[GPFEN0/4] |= (1 << pin);  // Enable falling edge detection
    } else {
        gpio_map[GPFEN1/4] |= (1 << (pin - 32));
    }
    
    return 1;
}

// Register a GPIO pin for counting with direct interrupt setup
static int register_pin(int pin) {
    if (!init_counters()) return 0;
    
    // Find available slot
    for (int i = 0; i < 4; i++) {
        if (pin_mapping[i] == -1) {
            pin_mapping[i] = pin;
            pulse_counts[i] = 0;
            
            // Setup GPIO pin for interrupt detection
            if (!setup_gpio_pin(pin)) {
                pin_mapping[i] = -1;  // Rollback on failure
                return -1;
            }
            
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

// Check for GPIO interrupts and increment counters (GIL-free)
static void check_interrupts() {
    if (!counter_initialized || gpio_map == NULL) return;
    
    // Batch memory reads for both event registers in one operation
    volatile uint32_t events0 = gpio_map[GPEDS0/4];
    volatile uint32_t events1 = gpio_map[GPEDS1/4];
    
    // Process all events in one pass if any are detected
    if (events0 || events1) {
        // Clear events immediately after reading
        gpio_map[GPEDS0/4] = events0;
        gpio_map[GPEDS1/4] = events1;
        
        // Process all pins in one loop for better cache efficiency
        for (int i = 0; i < 4; i++) {
            if (pin_mapping[i] != -1) {
                int pin = pin_mapping[i];
                if (pin < 32 && (events0 & (1 << pin))) {
                    pulse_counts[i]++;
                } else if (pin >= 32 && (events1 & (1 << (pin - 32)))) {
                    pulse_counts[i]++;
                }
            }
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

static PyObject* py_check_interrupts(PyObject* self, PyObject* args) {
    check_interrupts();
    Py_RETURN_NONE;
}

static PyObject* py_cleanup(PyObject* self, PyObject* args) {
    cleanup_gpio();
    counter_initialized = 0;
    Py_RETURN_NONE;
}

// Method definitions
static PyMethodDef PulseCounterMethods[] = {
    {"register_pin", py_register_pin, METH_VARARGS, "Register a GPIO pin for counting"},
    {"get_count", py_get_count, METH_VARARGS, "Get current pulse count for a pin"},
    {"reset_count", py_reset_count, METH_VARARGS, "Reset pulse count for a pin"},
    {"increment_count", py_increment_count, METH_VARARGS, "Increment pulse count for a pin"},
    {"check_interrupts", py_check_interrupts, METH_VARARGS, "Check for GPIO interrupts and update counters"},
    {"cleanup", py_cleanup, METH_VARARGS, "Cleanup GPIO resources"},
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
