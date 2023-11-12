import bisect
walk_search = []
transit_search = []
walk_search_nodes = {}
transit_search_nodes = {}


class SearchStart:
    def __init__(self, id, time):
        self.id = id
        self.time = time
        self.rte = 0
        self.dir = 0

    def set_route_dir(self, rte, dir):
        self.rte = rte
        self.dir = dir

    def __repr__(self):
        return f"id: {self.id}, time: {self.time}"

    def __lt__(self, other):
        return self.time < other.time


# Add all the stops encountered in previous search to future search origin nodes
def add_search_nodes(paths, key, search_list, dictionary, cutoff):
    for f in paths.getFeatures():
        feature_key = f[key]
        cost = f['cost']
        if not cost or cost > cutoff:
            continue
        if feature_key not in dictionary or dictionary[feature_key] > cost:
            dictionary[feature_key] = cost
            node = SearchStart(feature_key, cost)
            #if f[rte]:
                #node.
            bisect.insort(search_list, node)


# Update the dictionary with the times a trip departed from each stop on route
# Assume a sorted list of paths to each stop
# Will also clean the paths layer to remove unreachable stops
# And stops beyond another encountered, better, depart time
def update_network_dictionary(paths, cutoff):
    met_better_departure = False
    for f in paths.getFeatures():
        fid = f['fid']
        cost = f['cost']
        if cost and fid in transit_search_nodes and transit_search_nodes[fid] < cost:
            met_better_departure = True
        if not cost or cost > cutoff or met_better_departure is True:
            paths.deleteFeature(f.id())
            continue
        transit_search_nodes[fid] = cost


# Select next node from which to begin a search
def pick_next(search_list, dictionary):
    for next_node in search_list:
        # Only begin a search if the node in the sorted list has the same time as the node in the dictionary
        # Nodes may be entered multiple times if a faster start time is found
        # The dictionary entry will contain the fastest start time
        if dictionary[next_node.id] == next_node.time:
            return next_node
    return None


