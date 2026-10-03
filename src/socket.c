/*
 * This file is part of mod-host.
 *
 * mod-host is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * mod-host is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with mod-host.  If not, see <http://www.gnu.org/licenses/>.
 *
 */

/*
************************************************************************************************************************
*           INCLUDE FILES
************************************************************************************************************************
*/

#include <stdio.h>
#include <unistd.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <limits.h>

#ifdef _WIN32
#include <winsock2.h>
#else
#include <sys/socket.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#define closesocket close
#define INVALID_SOCKET -1
typedef int SOCKET;
#endif

#include "socket.h"
#include "effects.h"


/*
************************************************************************************************************************
*           LOCAL DEFINES
************************************************************************************************************************
*/


/*
************************************************************************************************************************
*           LOCAL CONSTANTS
************************************************************************************************************************
*/


/*
************************************************************************************************************************
*           LOCAL DATA TYPES
************************************************************************************************************************
*/


/*
************************************************************************************************************************
*           LOCAL MACROS
************************************************************************************************************************
*/


/*
************************************************************************************************************************
*           LOCAL GLOBAL VARIABLES
************************************************************************************************************************
*/

static SOCKET g_serverfd = INVALID_SOCKET;
static SOCKET g_fbserverfd = INVALID_SOCKET;
static SOCKET g_clientfd = INVALID_SOCKET;
static SOCKET g_fbclientfd = INVALID_SOCKET;

static int g_buffer_size;
static void (*g_receive_cb)(msg_t *msg);

/*
************************************************************************************************************************
*           LOCAL FUNCTION PROTOTYPES
************************************************************************************************************************
*/


/*
************************************************************************************************************************
*           LOCAL CONFIGURATION ERRORS
************************************************************************************************************************
*/


/*
************************************************************************************************************************
*           LOCAL FUNCTIONS
************************************************************************************************************************
*/


/*
************************************************************************************************************************
*           GLOBAL FUNCTIONS
************************************************************************************************************************
*/

int socket_start(int socket_port, int feedback_port, int buffer_size)
{
#ifdef _WIN32
    WSADATA wsaData;
    if (WSAStartup(MAKEWORD(2, 2), &wsaData) != 0)
    {
        perror("WSAStartup");
        return -1;
    }

    if (LOBYTE(wsaData.wVersion) != 2 || HIBYTE(wsaData.wVersion) != 2)
    {
        WSACleanup();
        perror("WSAStartup  version");
        return -1;
    }
#endif

    g_clientfd = g_fbclientfd = INVALID_SOCKET;
    g_serverfd = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);

    if (g_serverfd == INVALID_SOCKET)
    {
        perror("g_serverfd socket error");
        return -1;
    }

    if (feedback_port != 0)
    {
        g_fbserverfd = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);

        if (g_fbserverfd == INVALID_SOCKET)
        {
            perror("g_fbserverfd socket error");
            return -1;
        }
    }
    else
    {
        g_fbserverfd = INVALID_SOCKET;
    }

#ifndef _WIN32
    /* Allow the reuse of the socket address */
    int value = 1;
    setsockopt(g_serverfd, SOL_SOCKET, SO_REUSEPORT, &value, sizeof(value));
    if (feedback_port != 0)
        setsockopt(g_fbserverfd, SOL_SOCKET, SO_REUSEPORT, &value, sizeof(value));

    /* Set TCP_NODELAY */
    setsockopt(g_serverfd, IPPROTO_TCP, TCP_NODELAY, &value, sizeof(value));
    if (feedback_port != 0)
        setsockopt(g_fbserverfd, IPPROTO_TCP, TCP_NODELAY, &value, sizeof(value));

    /* Increase socket size */
    value = 131071;
    setsockopt(g_serverfd, SOL_SOCKET, SO_RCVBUF, &value, sizeof(value));
    if (feedback_port != 0)
        setsockopt(g_fbserverfd, SOL_SOCKET, SO_RCVBUF, &value, sizeof(value));
#endif

    /* Startup the socket struct */
    struct sockaddr_in serv_addr;
    memset(&serv_addr, 0, sizeof(serv_addr));
    serv_addr.sin_family = AF_INET;
#if defined(__MOD_DEVICES__) || defined(_WIN32)
    serv_addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
#else
    serv_addr.sin_addr.s_addr = htonl(INADDR_ANY);
#endif

    /* Try assign the server address */
    serv_addr.sin_port = htons(socket_port);
    if (bind(g_serverfd, (struct sockaddr *) &serv_addr, sizeof(serv_addr)) < 0)
    {
        perror("bind error");
        return -1;
    }

    if (feedback_port != 0)
    {
        /* Try assign the receiver address */
        serv_addr.sin_port = htons(feedback_port);
        if (bind(g_fbserverfd, (struct sockaddr *) &serv_addr, sizeof(serv_addr)) < 0)
        {
            perror("bind error");
            return -1;
        }
    }

    /* Start listen the sockets */
    if (listen(g_serverfd, -1) < 0)
    {
        perror("listen error");
        return -1;
    }

    if (feedback_port != 0 && listen(g_fbserverfd, -1) < 0)
    {
        perror("listen error");
        return -1;
    }

    g_receive_cb = NULL;
    g_buffer_size = buffer_size;

    return 0;
}


void socket_finish(void)
{
    if (g_serverfd == INVALID_SOCKET)
        return;

    // make local copies so that we can invalidate these vars first
    const SOCKET serverfd   = g_serverfd;
    const SOCKET fbserverfd = g_fbserverfd;
    g_serverfd = g_fbserverfd = INVALID_SOCKET;

    // shutdown clients, but don't close them
    if (g_fbclientfd != INVALID_SOCKET)
        shutdown(g_fbclientfd, SHUT_RDWR);
    shutdown(g_clientfd, SHUT_RDWR);

    // shutdown and close servers
    if (fbserverfd != INVALID_SOCKET)
    {
        shutdown(fbserverfd, SHUT_RDWR);
        closesocket(fbserverfd);
    }

    shutdown(serverfd, SHUT_RDWR);
    closesocket(serverfd);

#ifdef _WIN32
    WSACleanup();
#endif
}


void socket_set_receive_cb(void (*receive_cb)(msg_t *msg))
{
    g_receive_cb = receive_cb;
}


int socket_send(int destination, const char *buffer, int size)
{
    int ret = -1;

    while (size > 0)
    {
#ifdef MSG_NOSIGNAL
        ret = send(destination, buffer, size, MSG_NOSIGNAL);
#else
        ret = send(destination, buffer, size, 0);
#endif
#ifndef _WIN32
        if (ret < 0 && errno == EINTR)
            continue;
#endif
        if (ret <= 0)
        {
            perror("send error");
            return -1;
        }
        size -= ret;
        buffer += ret;
    }

    return ret;
}


int socket_send_feedback(const char *buffer)
{
    if (g_fbclientfd == INVALID_SOCKET) return -1;

    return socket_send(g_fbclientfd, buffer, strlen(buffer)+1);
}


void socket_run(int exit_on_failure)
{
    SOCKET clientfd, fbclientfd;
    int count;
    char *buffer;
    size_t buffered = 0;
    size_t capacity = g_buffer_size;
    msg_t msg;

    /* Allocates memory to receive buffer */
    buffer = malloc(g_buffer_size);
    if (buffer == NULL)
    {
        if (! exit_on_failure)
            return;

        perror("malloc error");
        exit(EXIT_FAILURE);
    }

    /* Wait for client connection */
    clientfd = accept(g_serverfd, NULL, NULL);
    if (clientfd == INVALID_SOCKET)
    {
        free(buffer);

        if (! exit_on_failure)
            return;

        perror("accept error");
        exit(EXIT_FAILURE);
    }

    if (g_fbserverfd != INVALID_SOCKET)
    {
        fbclientfd = accept(g_fbserverfd, NULL, NULL);
        if (fbclientfd == INVALID_SOCKET)
        {
            free(buffer);
            closesocket(clientfd);

            if (! exit_on_failure)
                return;

            perror("accept error");
            exit(EXIT_FAILURE);
        }
    }
    else
    {
        fbclientfd = INVALID_SOCKET;
    }

    g_clientfd = clientfd;
    g_fbclientfd = fbclientfd;

    while (g_serverfd != INVALID_SOCKET)
    {
        if (buffered == capacity)
        {
            if (capacity > INT_MAX - (size_t)g_buffer_size)
                break;

            char *const resized = realloc(buffer, capacity + g_buffer_size);
            if (resized == NULL)
                break;

            buffer = resized;
            capacity += g_buffer_size;
        }

        const size_t available = capacity - buffered;
        const int receive_size = available < (size_t)g_buffer_size ? (int)available : g_buffer_size;
        count = recv(clientfd, buffer + buffered, receive_size, 0);

#ifndef _WIN32
        if (count < 0 && errno == EINTR)
            continue;
#endif

        if (count > 0) /* Data received */
        {
            buffered += count;
            size_t consumed = 0;

            /* TCP packets do not define protocol boundaries. Keep incomplete
               commands until their NUL terminator arrives, and dispatch every
               complete command even when the next one is still incomplete. */
            while (consumed < buffered)
            {
                char *const frame = buffer + consumed;
                char *const end = memchr(frame, '\0', buffered - consumed);
                if (end == NULL)
                    break;

                const size_t frame_size = end - frame + 1;
                if (frame_size > 1 && g_receive_cb)
                {
                    msg.sender_id = clientfd;
                    msg.data = frame;
                    msg.data_size = frame_size;
                    g_receive_cb(&msg);
                }
                consumed += frame_size;
            }

            buffered -= consumed;
            if (buffered != 0 && consumed != 0)
                memmove(buffer, buffer + consumed, buffered);

            effects_idle_external_uis();
        }
        else if (count < 0) /* Error */
        {
            if (! exit_on_failure)
                break;

            perror("read error");
            exit(EXIT_FAILURE);
        }
        else /* Client disconnected */
        {
            break;
        }
    }

    if (fbclientfd != INVALID_SOCKET)
    {
        g_fbclientfd = INVALID_SOCKET;
        closesocket(fbclientfd);
    }

    g_clientfd = INVALID_SOCKET;
    closesocket(clientfd);

    free(buffer);
}
