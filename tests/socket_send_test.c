/* A disconnected peer must return an error without SIGPIPE or retry loops. */
#include "../src/socket.h"
#include <assert.h>
#include <sys/socket.h>
#include <unistd.h>

void effects_idle_external_uis(void);
void effects_idle_external_uis(void) {}

int main(void)
{
    int peers[2];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, peers) == 0);
    close(peers[1]);
    assert(socket_send(peers[0], "resp 0", 7) == -1);
    close(peers[0]);
    return 0;
}
