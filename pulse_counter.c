/*
 * GIL-free GPIO pulse counter using libgpiod v2 on 64-bit Linux.
 * Supports up to 2 concurrent pins with a background epoll thread.
 */

#include <Python.h>
#include <stdint.h>
#include <stdatomic.h>
#include <errno.h>
#include <pthread.h>
#include <unistd.h>
#include <sys/epoll.h>
#include <gpiod.h>

#define MAX_PINS 2

static atomic_uint_fast64_t pulse_counts[MAX_PINS];
static int pin_offsets[MAX_PINS] = {-1, -1};
static int num_registered = 0;

static struct gpiod_chip *chip = NULL;
static struct gpiod_request *request = NULL;
static int request_fd = -1;
static int epoll_fd = -1;
static pthread_t event_thread;
static int thread_running = 0;

// Internal: find slot index for a pin offset
static int find_slot(int pin) {
    for (int i = 0; i < MAX_PINS; i++) {
        if (pin_offsets[i] == pin) return i;
    }
    return -1;
}

// Thread loop: wait for edge events and increment counters
static void *event_loop(void *arg) {
    (void)arg;
    struct gpiod_edge_event_buffer *buffer = gpiod_edge_event_buffer_new(32);
    if (!buffer) {
        thread_running = 0;
        return NULL;
    }

    struct epoll_event ev;
    while (thread_running) {
        int n = epoll_wait(epoll_fd, &ev, 1, 500);
        if (!thread_running) break;
        if (n <= 0) {
            continue;
        }
        if (ev.data.fd == request_fd) {
            int readn;
            do {
                readn = gpiod_request_read_edge_events(request, buffer, 32);
                if (readn <= 0) break;
                for (int i = 0; i < readn; i++) {
                    const struct gpiod_edge_event *e = gpiod_edge_event_buffer_get_event(buffer, i);
                    if (!e) continue;
                    unsigned int off = gpiod_edge_event_get_line_offset(e);
                    int slot = find_slot((int)off);
                    if (slot >= 0) {
                        atomic_fetch_add_explicit(&pulse_counts[slot], 1, memory_order_relaxed);
                    }
                }
            } while (readn > 0);
        }
    }

    gpiod_edge_event_buffer_free(buffer);
    return NULL;
}

// Build a gpiod request for currently registered pins
static int build_request(void) {
    if (num_registered <= 0) {
        errno = EINVAL;
        return -1;
    }

    chip = gpiod_chip_open_by_name("gpiochip0");
    if (!chip) return -1;

    struct gpiod_line_settings *settings = gpiod_line_settings_new();
    if (!settings) return -1;
    gpiod_line_settings_set_direction(settings, GPIOD_LINE_DIRECTION_INPUT);
    gpiod_line_settings_set_edge_detection(settings, GPIOD_LINE_EDGE_FALLING);
    // Optional: enable pull-up if desired (depends on board wiring)
    // gpiod_line_settings_set_bias(settings, GPIOD_LINE_BIAS_PULL_UP);

    struct gpiod_line_config *lcfg = gpiod_line_config_new();
    if (!lcfg) { gpiod_line_settings_free(settings); return -1; }
    if (gpiod_line_config_add_line_settings(lcfg, (const unsigned int *)pin_offsets, num_registered, settings) < 0) {
        gpiod_line_settings_free(settings);
        gpiod_line_config_free(lcfg);
        return -1;
    }

    struct gpiod_request_config *rcfg = gpiod_request_config_new();
    if (!rcfg) {
        gpiod_line_settings_free(settings);
        gpiod_line_config_free(lcfg);
        return -1;
    }
    gpiod_request_config_set_consumer(rcfg, "pulse_counter");

    request = gpiod_chip_request_lines(chip, rcfg, lcfg);
    gpiod_request_config_free(rcfg);
    gpiod_line_config_free(lcfg);
    gpiod_line_settings_free(settings);
    if (!request) return -1;

    request_fd = gpiod_request_get_fd(request);
    if (request_fd < 0) return -1;

    epoll_fd = epoll_create1(EPOLL_CLOEXEC);
    if (epoll_fd < 0) return -1;
    struct epoll_event ev;
    ev.events = EPOLLIN;
    ev.data.fd = request_fd;
    if (epoll_ctl(epoll_fd, EPOLL_CTL_ADD, request_fd, &ev) < 0) return -1;

    return 0;
}

static void release_request(void) {
    if (epoll_fd >= 0) { close(epoll_fd); epoll_fd = -1; }
    request_fd = -1;
    if (request) { gpiod_request_release(request); request = NULL; }
    if (chip) { gpiod_chip_close(chip); chip = NULL; }
}

// API: register pin, returns slot index (0..1) or -1
static int register_pin_internal(int pin) {
    if (num_registered >= MAX_PINS) return -1;
    if (find_slot(pin) >= 0) return find_slot(pin);
    for (int i = 0; i < MAX_PINS; i++) {
        if (pin_offsets[i] == -1) {
            pin_offsets[i] = pin;
            atomic_store_explicit(&pulse_counts[i], 0, memory_order_relaxed);
            num_registered++;
            return i;
        }
    }
    return -1;
}

// Python wrappers
static PyObject* py_register_pin(PyObject* self, PyObject* args) {
    int pin;
    if (!PyArg_ParseTuple(args, "i", &pin)) {
        return NULL;
    }
    if (thread_running) {
        PyErr_SetString(PyExc_RuntimeError, "Cannot register pin after start()");
        return NULL;
    }
    int slot = register_pin_internal(pin);
    if (slot < 0) {
        PyErr_SetString(PyExc_RuntimeError, "No available slots or duplicate pin");
        return NULL;
    }
    return PyLong_FromLong(slot);
}

static PyObject* py_start(PyObject* self, PyObject* args) {
    if (thread_running) Py_RETURN_NONE;
    if (num_registered <= 0) {
        PyErr_SetString(PyExc_RuntimeError, "No pins registered");
        return NULL;
    }
    int rc;
    Py_BEGIN_ALLOW_THREADS
    rc = build_request();
    if (rc == 0) {
        thread_running = 1;
        if (pthread_create(&event_thread, NULL, event_loop, NULL) != 0) {
            thread_running = 0;
            release_request();
            rc = -1;
        }
    }
    Py_END_ALLOW_THREADS
    if (rc != 0) {
        PyErr_SetString(PyExc_RuntimeError, "Failed to start event thread");
        return NULL;
    }
    Py_RETURN_NONE;
}

static PyObject* py_stop(PyObject* self, PyObject* args) {
    if (!thread_running) Py_RETURN_NONE;
    thread_running = 0;
    // Nudge epoll with a short sleep to unblock
    Py_BEGIN_ALLOW_THREADS
    pthread_join(event_thread, NULL);
    release_request();
    Py_END_ALLOW_THREADS
    Py_RETURN_NONE;
}

static PyObject* py_get_count(PyObject* self, PyObject* args) {
    int pin;
    if (!PyArg_ParseTuple(args, "i", &pin)) {
        return NULL;
    }
    int slot = find_slot(pin);
    if (slot < 0) {
        return PyLong_FromUnsignedLongLong(0);
    }
    uint64_t val = atomic_load_explicit(&pulse_counts[slot], memory_order_relaxed);
    return PyLong_FromUnsignedLongLong(val);
}

static PyObject* py_reset_count(PyObject* self, PyObject* args) {
    int pin;
    if (!PyArg_ParseTuple(args, "i", &pin)) {
        return NULL;
    }
    int slot = find_slot(pin);
    if (slot >= 0) {
        atomic_store_explicit(&pulse_counts[slot], 0, memory_order_relaxed);
    }
    Py_RETURN_NONE;
}

// Test helper: bump counter directly (not an emulator of hardware)
static PyObject* py_trigger_interrupt(PyObject* self, PyObject* args) {
    int pin, count;
    if (!PyArg_ParseTuple(args, "ii", &pin, &count)) {
        return NULL;
    }
    int slot = find_slot(pin);
    if (slot < 0) {
        PyErr_SetString(PyExc_ValueError, "Pin not registered");
        return NULL;
    }
    if (count > 0) {
        atomic_fetch_add_explicit(&pulse_counts[slot], (uint64_t)count, memory_order_relaxed);
    }
    return PyLong_FromLong(count);
}

static PyObject* py_check_interrupts(PyObject* self, PyObject* args) {
    // No-op for compatibility; events are handled in background thread
    Py_RETURN_NONE;
}

static PyObject* py_cleanup(PyObject* self, PyObject* args) {
    if (thread_running) {
        thread_running = 0;
        Py_BEGIN_ALLOW_THREADS
        pthread_join(event_thread, NULL);
        Py_END_ALLOW_THREADS
    }
    release_request();
    for (int i = 0; i < MAX_PINS; i++) {
        pin_offsets[i] = -1;
        atomic_store_explicit(&pulse_counts[i], 0, memory_order_relaxed);
    }
    num_registered = 0;
    Py_RETURN_NONE;
}

// Method definitions
static PyMethodDef PulseCounterMethods[] = {
    {"register_pin", py_register_pin, METH_VARARGS, "Register a GPIO pin (BCM offset)"},
    {"start", py_start, METH_VARARGS, "Start background edge handling"},
    {"stop", py_stop, METH_VARARGS, "Stop background edge handling"},
    {"get_count", py_get_count, METH_VARARGS, "Get current pulse count for a pin"},
    {"reset_count", py_reset_count, METH_VARARGS, "Reset pulse count for a pin"},
    {"trigger_interrupt", py_trigger_interrupt, METH_VARARGS, "Test helper: bump counter (not hardware)"},
    {"check_interrupts", py_check_interrupts, METH_VARARGS, "No-op; kept for compatibility"},
    {"cleanup", py_cleanup, METH_VARARGS, "Cleanup resources"},
    {NULL, NULL, 0, NULL}
};

// Module definition
static struct PyModuleDef pulse_counter_module = {
    PyModuleDef_HEAD_INIT,
    "pulse_counter",
    "GIL-free GPIO pulse counter using libgpiod v2",
    -1,
    PulseCounterMethods
};

PyMODINIT_FUNC PyInit_pulse_counter(void) {
    for (int i = 0; i < MAX_PINS; i++) {
        pin_offsets[i] = -1;
        atomic_store_explicit(&pulse_counts[i], 0, memory_order_relaxed);
    }
    return PyModule_Create(&pulse_counter_module);
}
