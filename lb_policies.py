import time

# coding: utf-8

# n to 1 policy
class N2One:
    def __init__(self, servers):
        self.servers = servers

    def select_server(self):
        return self.servers[0]

    def update(self, *arg):
        pass


# round robin policy
class RoundRobin:
    def __init__(self, servers):
        self.servers = servers
        self.current_index = 0  #index to keep track of the last server used

    def select_server(self):
        #select server at current index and update the index for next request
        server = self.servers[self.current_index]
        self.current_index = (self.current_index + 1) % len(self.servers)
        return server

    def update(self, *arg):
        #this policy also doesn't track state, so nothing to update
        pass


# least connections policy
class LeastConnections:
    def __init__(self, servers):
        self.servers = servers
        self.connections = {server: 0 for server in servers}  #track current connections per server

    def select_server(self):
        #select the server with the fewest active connections
        server = min(self.connections, key=self.connections.get)
        self.connections[server] += 1  #simulate assigning a new connection
        return server

    def update(self, *arg):
        #called when a request finishes; decrease the server's connection count
        conn = arg[0]
        if conn in self.connections:
            self.connections[conn] -= 1
            if self.connections[conn] < 0:
                self.connections[conn] = 0  #ensure no negative values


# least response time
class LeastResponseTime:
    def __init__(self, servers):
        self.servers = servers
        self.average_time = {server: 0 for server in servers}  #average response time per server
        self.start_times = {server: 0 for server in servers}  #stores start times of ongoing requests (keyed by server)
        self.response_times = {server: [] for server in servers}  #all response times per server

    def select_server(self):
        now = time.time() #assuming a new request starts now (adjusted estimation)

        #calculate the expected average response time for each server
        for srv in self.servers:
            #duration is the time between the last start and now (negative if not started yet)
            duration = self.start_times[srv] - now

            #calculate the new estimated average with this potential new duration
            total_time = sum(self.response_times[srv]) + duration
            self.average_time[srv] = total_time / (len(self.response_times[srv]) + 1)

        #choose the server with the lowest estimated average response time
        selected = min(self.average_time, key=self.average_time.get)

        #record the start time of the request to calculate actual duration later
        self.start_times[selected] = time.time()

        return selected

    def update(self, *args):
        if not args:
            raise ValueError("Missing server to update")

        srv = args[0]

        #calculate the actual duration of the request for this server
        elapsed = time.time() - self.start_times[srv]

        #store this new response time
        self.response_times[srv].append(elapsed)

        #recalculate the average response time for this server
        total = sum(self.response_times[srv])
        self.average_time[srv] = total / len(self.response_times[srv])