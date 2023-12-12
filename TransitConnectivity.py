import bisect
from qgis.core import QgsProcessingFeatureSourceDefinition
import ProjectInteraction
next_nodes = []
walk_nodes_dictionary = {}
transit_nodes_dictionary = {}
repeat_search_threshold = 1.0


class SearchStart:
    def __init__(self, identifier, layer, time, dictionary, is_transit_node, is_search_origin):
        self.id = identifier
        self.layer = layer
        self.time = time
        self.dictionary = dictionary
        self.is_transit_node = is_transit_node
        self.is_search_origin = is_search_origin

    def set_route_dir(self, rte, dir):
        self.rte = rte
        self.dir = dir

    def get_coord_string(self):
        feature = next(self.layer.getFeatures(QgsFeatureRequest().setFilterFid(self.id)))
        geo_point = feature.geometry().asPoint()
        return f"{geo_point.x()},{geo_point.y()} [{self.layer.crs().authid()}]"

    def __repr__(self):
        mode = "transit" if self.is_transit_node else "walking"
        return f"id: {self.id}, mode: {mode}, time: {self.time}"

    def __lt__(self, other):
        return self.time < other.time


def should_add_search_node(key, dictionary, time):
    if key not in dictionary:
        return True

    #return time < dictionary[key]


    time_remaining = total_time - time
    prev_time_remaining = total_time - dictionary[key]
    if time_remaining > prev_time_remaining * repeat_search_threshold:
        return True

    return False


# Takes a path to a new node and adds it to correct list
def add_search_node(feature, departing_time, add_to_walk_search, next_dictionary, next_layer):
    if departing_time >= total_time:
        return
    feature_key = get_correct_fid(feature, add_to_walk_search)

    if should_add_search_node(feature_key, next_dictionary, departing_time):
        next_dictionary[feature_key] = departing_time
        node = SearchStart(feature_key,
                           next_layer,
                           departing_time, next_dictionary, not add_to_walk_search, False)
        if not add_to_walk_search:
            node.set_route_dir(feature['rte'], feature['dir'])
        if next_nodes:
            bisect.insort(next_nodes, node)
        else:
            next_nodes.append(node)


# Iterates over stops encountered in a search
# If a stop has a cost associated with it (it could be reached), sends it off for saving
def add_search_nodes(paths, node, add_to_walk_search):
    next_search_layer = stops_layer if add_to_walk_search else route_stops_layer
    next_dictionary = walk_nodes_dictionary if add_to_walk_search else transit_nodes_dictionary

    for f in paths:
        if f['cost']:
            if node.is_search_origin or add_to_walk_search:
                departure_time = node.time + f['cost']
            else:
                # Select the route that will depart from this stop
                select_by_route(routes_layer, f['rte'], f['dir'])
                if not routes_layer.selectedFeatures():
                    continue
                next_route = routes_layer.selectedFeatures()[0]
                if next_route['TRIP_PR_HR'] == 0:
                    continue

                # Average wait is half of the headway of the route
                avg_wait = (1 / next_route['TRIP_PR_HR']) / 2
                departure_time = node.time + f['cost'] + avg_wait
                routes_layer.removeSelection()

            add_search_node(f, departure_time, add_to_walk_search, next_dictionary, next_search_layer)


# Get the feature ID for the correct layer
#   If the search that yielded this feature was a transit search:
#       Node to be added should be from simple stops layer, with its fid
#   Otherwise, just add the fid from what was the route_stops layer
def get_correct_fid(feature, get_stop_fid):
    if get_stop_fid:
        stop_id = str(feature['stop_id'])
        expr = QgsExpression("stop_id = " + stop_id)
        stop_feature = next(stops_layer.getFeatures(QgsFeatureRequest(expr)))
        return stop_feature['fid']
    return feature['fid']


def update_walking_dictionary(path_features, start_search_time):
    for f in path_features:
        cost = f['cost']

        feature_key = get_correct_fid(f, True)
        if cost:
            if (feature_key not in walk_nodes_dictionary.keys() or
                    start_search_time + cost < walk_nodes_dictionary[feature_key]):
                walk_nodes_dictionary[feature_key] = start_search_time + cost

# Update the dictionary with the times a trip departed from each stop on route
# Assume a sorted list of paths to each stop
# Will also clean the paths layer to remove unreachable stops
# And stops beyond another encountered, better, depart time
def update_network_dictionary(path_features, start_search_time):
    met_better_departure = False
    for f in path_features:
        fid = f['fid']
        cost = f['cost']
        if cost and fid in transit_nodes_dictionary and transit_nodes_dictionary[fid] < start_search_time + cost:
            met_better_departure = True
        if not met_better_departure and cost:
            transit_nodes_dictionary[fid] = start_search_time + cost


# Select next node from which to begin a search
def pick_next():
    # If no more searchable nodes, return none
    if not next_nodes: return

    # Get next candidate by popping it from list
    node = next_nodes.pop(0)

    # Only begin a search if the node in the search list has the same time as it's dictionary match
    # Nodes may be entered multiple times if a faster start time is found
    # The dictionary entry will contain the fastest start time
    if node.time == node.dictionary[node.id]:
        return node

    return pick_next()




def sort_paths_by_cost(paths):
    request = qgis.core.QgsFeatureRequest()

    # set order by field
    clause = qgis.core.QgsFeatureRequest.OrderByClause('cost', ascending=False)
    orderby = qgis.core.QgsFeatureRequest.OrderBy([clause])
    request.setOrderBy(orderby)

    return paths.getFeatures(request)

def print_dictionary(dictionary):
    print("Dictionary:")
    for elem in dictionary:
        print(f"    {elem}")


def print_search_list():
    print("Next/potential search nodes:")
    for elem in next_nodes[slice(10)]:
        print(f"    {elem}")
    print("    ... ")


def perform_transit_search(node):
    paths_to_stops = get_reachable_stops_transit(node)
    path_features_sorted = sort_paths_by_cost(paths_to_stops)
    #print(f"Sorted path features: {path_features_sorted} and len: {len(list(path_features_sorted))}")
    update_network_dictionary(path_features_sorted,node.time)
    add_search_nodes(paths_to_stops.getFeatures(), node, True)


def perform_walk_search(node):
    paths_to_stops = get_reachable_stops_walking(node)
    update_walking_dictionary(paths_to_stops.getFeatures(),node.time)
    path_features_sorted = sort_paths_by_cost(paths_to_stops)
    add_search_nodes(path_features_sorted, node, False)


def perform_search():
    count = 0
    while next_nodes:
        count+=1
        print_search_list()

        search_origin = pick_next()
        if search_origin:
            mode = "transit" if search_origin.is_transit_node else "walking"
            print(f"Beginning {mode} search from point {search_origin.id}")

            if search_origin.is_transit_node:
                perform_transit_search(search_origin)
            else:
                perform_walk_search(search_origin)
        #if count >= 20:
           #return
    print("All done!")
    get_walking_service_area(walk_nodes_dictionary)
    get_transit_service_area()


def init_search():
    init_node = SearchStart(7946, route_stops_layer, 0,
        transit_nodes_dictionary, False, True)
    next_nodes.append(init_node)
    init_node.dictionary[init_node.id] = init_node.time
    perform_search()

init_search()