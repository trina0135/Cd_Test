import socket
import selectors
import signal
import logging
import argparse
from lb_policies import N2One, RoundRobin, LeastConnections, LeastResponseTime

POLICIES = {
    "N2One": N2One,
    "RoundRobin": RoundRobin,
    "LeastConnections": LeastConnections,
    "LeastResponseTime": LeastResponseTime
}

logging.basicConfig(level=logging.DEBUG,
                   format='%(asctime)s %(name)-12s %(levelname)-8s %(message)s',
                   datefmt='%m-%d %H:%M:%S')
logger = logging.getLogger('Load Balancer')

class BalancerInterrupted(Exception):
    pass

def graceful_shutdown(signalNumber, frame):
    logger.debug('Graceful Shutdown...')
    raise BalancerInterrupted()

class SocketMapper:
    def __init__(self, policy, sel):
        self.policy = policy
        self.map = {}
        self.sel = sel
        self.cache = {}
        self.cache_order = []
        self.cache_size = 5
        self.cache_hits = 0
        self.cache_misses = 0
        self.pending_requests = {}  # upstream_sock -> request_data

    def add(self, client_sock, upstream_server):
        client_sock.setblocking(False)
        self.sel.register(client_sock, selectors.EVENT_READ, read)
        upstream_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        upstream_sock.connect(upstream_server)
        upstream_sock.setblocking(False)
        self.sel.register(upstream_sock, selectors.EVENT_READ, read)
        logger.debug("Proxying to %s %s", *upstream_server)
        self.map[client_sock] = upstream_sock

    def delete(self, sock):
        paired_sock = self.get_sock(sock)
        self.sel.unregister(sock)
        sock.close()
        self.sel.unregister(paired_sock)
        paired_sock.close()
        if sock in self.map:
            self.map.pop(sock)
        else:
            self.map.pop(paired_sock)

    def get_sock(self, sock):
        for client, upstream in self.map.items():
            if upstream == sock:
                return client
            if client == sock:
                return upstream
        return None

    def get_upstream_sock(self, sock):
        return self.map.get(sock)

    def get_all_socks(self):
        return list(sum(self.map.items(), ()))

    def get_policy(self):
        return self.policy

    def check_cache(self, request):
        if request in self.cache:
            self.cache_order.remove(request)
            self.cache_order.append(request)
            self.cache_hits += 1
            logger.debug(f"[CACHE HIT] Total hits: {self.cache_hits}")
            return self.cache[request]
        self.cache_misses += 1
        logger.debug(f"[CACHE MISS] Total misses: {self.cache_misses}")
        return None

    def add_to_cache(self, request, response):
        if len(self.cache) >= self.cache_size:
            oldest = self.cache_order.pop(0)
            del self.cache[oldest]
        self.cache[request] = response
        self.cache_order.append(request)
        logger.debug(f"Added to cache: {request[:50]}...")

def accept(sock, mask, mapper):
    client, addr = sock.accept()
    logger.debug("Accepted connection %s %s", *addr)
    mapper.add(client, mapper.get_policy().select_server())

def read(conn, mask, mapper):
    data = conn.recv(4096)
    if len(data) == 0:
        mapper.delete(conn)
        return

    paired_sock = mapper.get_sock(conn)

    if conn in mapper.map:  # conn é socket cliente
        cached_response = mapper.check_cache(data)
        if cached_response:
            logger.debug("Serving response from cache")
            conn.send(cached_response)
            return

        # Cache miss → envia pedido ao servidor e guarda para associar resposta
        paired_sock.send(data)
        mapper.pending_requests[paired_sock] = data

    else:
        # conn é socket servidor → resposta do backend
        client_sock = mapper.get_sock(conn)
        if client_sock is None:
            return

        request_data = mapper.pending_requests.get(conn)
        if request_data:
            mapper.add_to_cache(request_data, data)
            del mapper.pending_requests[conn]

        client_sock.send(data)

def main(addr, servers, policy_class):
    signal.signal(signal.SIGINT, graceful_shutdown)

    policy = policy_class(servers)
    sel = selectors.DefaultSelector()
    mapper = SocketMapper(policy, sel)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(addr)
    sock.listen()
    sock.setblocking(False)

    sel.register(sock, selectors.EVENT_READ, accept)

    try:
        logger.debug("Listening on %s %s", *addr)
        while True:
            events = sel.select(timeout=1)
            for key, mask in events:
                if key.fileobj.fileno() > 0:
                    callback = key.data
                    callback(key.fileobj, mask, mapper)
    except BalancerInterrupted:
        logger.info('Balancer Stopped')
    except Exception as err:
        logger.error(err)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='HTTP Load Balancer')
    parser.add_argument('-a', dest='policy', choices=POLICIES.keys(), required=True,
                       help='Load balancing policy')
    parser.add_argument('-p', dest='port', type=int, default=8080,
                       help='Load balancer port')
    parser.add_argument('-s', dest='servers', nargs='+', type=int, required=True,
                       help='List of server ports')
    args = parser.parse_args()

    servers = [('localhost', p) for p in args.servers]
    main(('127.0.0.1', args.port), servers, POLICIES[args.policy])
