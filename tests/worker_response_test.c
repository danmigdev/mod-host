/* Incomplete responses must remain queued without blocking the audio thread. */
#include "../src/worker.h"
#include <assert.h>
#include <stdlib.h>
#include <string.h>

static unsigned int calls;
static LV2_Worker_Status response(LV2_Handle handle, uint32_t size, const void *data)
{
    (void)handle;
    assert(size == 5);
    assert(memcmp(data, "hello", size) == 0);
    ++calls;
    return LV2_WORKER_SUCCESS;
}

int main(void)
{
    const LV2_Worker_Interface iface = {NULL, response, NULL};
    LilvInstance instance;
    memset(&instance, 0, sizeof(instance));
    worker_t worker;
    memset(&worker, 0, sizeof(worker));
    worker.iface = &iface;
    worker.instance = &instance;
    worker.responses = jack_ringbuffer_create(128);
    worker.response = malloc(128);
    assert(worker.responses && worker.response);
    const uint32_t size = 5;

    jack_ringbuffer_write(worker.responses, (const char *)&size, 2);
    worker_emit_responses(&worker);
    assert(calls == 0 && jack_ringbuffer_read_space(worker.responses) == 2);

    jack_ringbuffer_write(worker.responses, (const char *)&size + 2, sizeof(size) - 2);
    jack_ringbuffer_write(worker.responses, "he", 2);
    worker_emit_responses(&worker);
    assert(calls == 0 && jack_ringbuffer_read_space(worker.responses) == sizeof(size) + 2);

    jack_ringbuffer_write(worker.responses, "llo", 3);
    worker_emit_responses(&worker);
    assert(calls == 1 && jack_ringbuffer_read_space(worker.responses) == 0);
    jack_ringbuffer_free(worker.responses);
    free(worker.response);
    return 0;
}
