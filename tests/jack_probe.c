/* A real JACK audio/MIDI client used by integration_test.py. */
#include <jack/jack.h>
#include <jack/midiport.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

static jack_port_t *audio_out, *audio_in, *midi_out;
static volatile unsigned int cycles;
static double sum;
static unsigned int samples;
static int send_midi;

static int process(jack_nframes_t nframes, void *arg)
{
    (void)arg;
    float *out = jack_port_get_buffer(audio_out, nframes);
    const float *in = jack_port_get_buffer(audio_in, nframes);
    void *midi = jack_port_get_buffer(midi_out, nframes);
    jack_midi_clear_buffer(midi);
    for (jack_nframes_t i = 0; i < nframes; ++i)
        out[i] = 0.125f;
    if (send_midi && cycles == 30)
    {
        const unsigned char event[] = {0xb0, 7, 64};
        jack_midi_event_write(midi, 0, event, sizeof(event));
    }
    if (cycles >= 100 && cycles < 140)
    {
        for (jack_nframes_t i = 0; i < nframes; ++i)
            sum += fabs(in[i]);
        samples += nframes;
    }
    ++cycles;
    return 0;
}

int main(int argc, char **argv)
{
    send_midi = argc > 1;
    (void)argv;
    jack_status_t status;
    jack_client_t *client = jack_client_open("integration-probe", JackNoStartServer, &status);
    if (!client)
        return 1;
    audio_out = jack_port_register(client, "out", JACK_DEFAULT_AUDIO_TYPE, JackPortIsOutput, 0);
    audio_in = jack_port_register(client, "in", JACK_DEFAULT_AUDIO_TYPE, JackPortIsInput, 0);
    midi_out = jack_port_register(client, "midi", JACK_DEFAULT_MIDI_TYPE, JackPortIsOutput, 0);
    if (!audio_out || !audio_in || !midi_out || jack_set_process_callback(client, process, NULL) || jack_activate(client))
        return 2;
    if (jack_connect(client, jack_port_name(audio_out), "effect_0:in") ||
        jack_connect(client, "effect_0:out", jack_port_name(audio_in)))
        return 3;
    if (send_midi && jack_connect(client, jack_port_name(midi_out), "mod-host:midi_in"))
        return 4;
    for (unsigned int i = 0; cycles < 160 && i < 500; ++i)
        usleep(10000);
    jack_deactivate(client);
    jack_client_close(client);
    if (cycles < 160 || samples == 0)
        return 5;
    printf("%.9f\n", sum / samples);
    return 0;
}
