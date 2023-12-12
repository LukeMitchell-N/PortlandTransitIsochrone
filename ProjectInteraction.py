from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (QgsProcessing,
                       QgsProcessingException,
                       QgsProcessingAlgorithm,
                       QgsFeature,
                       QgsProject,
                       QgsProcessingFeatureSourceDefinition)
from qgis import processing

point_name = 'start_point_test'
streets_name = '1HrWalkableRoads_NoHighways'
route_stops_name = 'trimet_route_stops'
stops_name = 'trimet_stops'
routes_name = 'trimetroutes_kph'

start_point_layer = QgsProject.instance().mapLayersByName(point_name)[0]
street_layer = QgsProject.instance().mapLayersByName(streets_name)[0]
route_stops_layer = QgsProject.instance().mapLayersByName(route_stops_name)[0]
stops_layer = QgsProject.instance().mapLayersByName(stops_name)[0]
routes_layer = QgsProject.instance().mapLayersByName(routes_name)[0]

service_areas = []
transit_routes = []

total_time = .15
walk_feet_per_hour = 14784  #feet walkable in one hour \
    #assuming a walking speed of 2.8 mph
walk_km_per_hour = 4.50616
ft_to_m = 3.28084



#finds the time to reach each stop within a street network
def find_stops_walking(start_node, network, stops):
    # get the coordinates as a string from the start node
    lat_lon_str = start_node.get_coord_string()

    # Note: due to this algorithm calculating distances on these layers in feet,
    #   we have to multiply the km/hr by ft_to_meters to get the correct times
    reachable_stops = processing.run("native:shortestpathpointtolayer", \
        {'INPUT':network,'STRATEGY': 1,'DIRECTION_FIELD':'',\
        'VALUE_FORWARD':'','VALUE_BACKWARD':'','VALUE_BOTH':'',\
        'DEFAULT_DIRECTION':2,'SPEED_FIELD':'','DEFAULT_SPEED': ft_to_m * walk_km_per_hour,\
        'TOLERANCE':0,'START_POINT':lat_lon_str,'END_POINTS':stops,\
        'OUTPUT':'TEMPORARY_OUTPUT'})['OUTPUT']
    reachable_stops.setName(f"walking_routes from id {start_node.id}")
    #QgsProject.instance().addMapLayer(reachable_stops)
    return reachable_stops


def find_stops_transit(start_node, route, stops):
    # Select the starting stop by pulling it from the stops layer
    #start_stop = next(route_stops_layer.getFeatures(QgsFeatureRequest().setFilterFid(start_node.id)))

    # Get the starting coordinates as a string from the start node
    lat_lon_str = start_node.get_coord_string() # get_coord_string(start_stop.geometry().asPoint())

    # Get the path to the route and stops
    #   (Necessary for running this process with only selected features)
    route_uri = route.dataProvider().dataSourceUri()
    stops_uri = stops.dataProvider().dataSourceUri()

    direction = start_node.dir
    reverse = 1 if direction == 0 else 0

    routes_to_stops = processing.run("native:shortestpathpointtolayer",
                                     {'INPUT': QgsProcessingFeatureSourceDefinition(
                                         route_uri,
                                         selectedFeaturesOnly=True, featureLimit=-1,
                                         geometryCheck=QgsFeatureRequest.GeometryAbortOnInvalid),
                                         'STRATEGY': 1, 'DIRECTION_FIELD': 'DIR', 'VALUE_FORWARD': direction,
                                         'VALUE_BACKWARD': reverse, 'VALUE_BOTH': '', 'DEFAULT_DIRECTION': direction,
                                         'SPEED_FIELD': 'K_FT_PR_HR', 'DEFAULT_SPEED': 50, 'TOLERANCE': 0,
                                         'START_POINT': lat_lon_str,
                                         'END_POINTS': QgsProcessingFeatureSourceDefinition(
                                             stops_uri,
                                             selectedFeaturesOnly=True, featureLimit=-1,
                                             geometryCheck=QgsFeatureRequest.GeometryAbortOnInvalid),
                                         'OUTPUT': 'TEMPORARY_OUTPUT'})['OUTPUT']
    routes_to_stops.setName(f"transit_routes from id {start_node.id}")
    #QgsProject.instance().addMapLayer(routes_to_stops)
    return routes_to_stops


def get_reachable_stops_walking(start_node):
    # Create buffer around start point with radius of
    # The maximum distance walkable with time remaining
    max_distance = walk_feet_per_hour * (total_time - start_node.time)
    buffer = create_buffer(start_node, max_distance)

    # Clip the street layer to only search relevant streets
    potential_streets = clip_layer(street_layer, buffer, "clipped streets")

    # Clip stop layer to only search relevant stops
    potential_stops = clip_layer(route_stops_layer, buffer, "clipped stops")

    # Search the network to find all reachable stops
    search_routes = find_stops_walking(start_node, potential_streets, potential_stops)

    service_area = create_service_area(start_node, potential_streets)

    # Get rid of all stops that exceed the time remaining
    remove_unreachable_stops(search_routes, start_node.time)

    QgsProject.instance().addMapLayer(search_routes)

    return search_routes

def get_reachable_stops_transit(start_node):

    # Select the route and stops that match the start node's rte and dir
    select_by_route(routes_layer, start_node.rte, start_node.dir)
    select_by_route(route_stops_layer, start_node.rte, start_node.dir)

    # Get the paths (portions of the route) from the start node to all stops on the route
    search_routes = find_stops_transit(start_node, routes_layer, route_stops_layer)

    routes_layer.removeSelection()
    route_stops_layer.removeSelection()

    # Get rid of all stops that exceed the time remaining
    remove_unreachable_stops(search_routes, start_node.time)

    transit_routes.append(search_routes)

    QgsProject.instance().addMapLayer(search_routes)

    return search_routes


def create_service_area(start_node, streets):
    lat_lon_str = start_node.get_coord_string()

    service_area = processing.run("native:serviceareafrompoint", {
        'INPUT': streets,
        'STRATEGY': 1, 'DIRECTION_FIELD': '', 'VALUE_FORWARD': '', 'VALUE_BACKWARD': '', 'VALUE_BOTH': '',
        'DEFAULT_DIRECTION': 2, 'SPEED_FIELD': '', 'DEFAULT_SPEED': ft_to_m * walk_km_per_hour, 'TOLERANCE': 0,
        'START_POINT': lat_lon_str, 'TRAVEL_COST2': start_node.time, 'INCLUDE_BOUNDS': False,
        'OUTPUT_LINES': 'TEMPORARY_OUTPUT'})['OUTPUT_LINES']

    service_areas.append(service_area)

def get_walking_service_area(walk_nodes_dictionary):
    reachable_stops = create_reachable_stops_layer(walk_nodes_dictionary)

    merged_layer = processing.run("qgis:mergevectorlayers", {
        'LAYERS': service_areas,
        'OUTPUT':  'TEMPORARY_OUTPUT'})['OUTPUT']
    merged_layer.setName("Walking Service Area")

    QgsProject.instance().addMapLayer(merged_layer)

def get_transit_service_area():
    merged_layer = processing.run("qgis:mergevectorlayers", {
        'LAYERS': transit_routes,
        'OUTPUT': 'TEMPORARY_OUTPUT'})['OUTPUT']
    merged_layer.setName("Transit Service Area")

    QgsProject.instance().addMapLayer(merged_layer)


# ********************************************************************************************************

# Create buffer around the point indicated by a node's layer and id
# Returns the vector layer containing the buffer
def create_buffer(node, distance):

    select_feature_by_attribute(node.layer, 'fid', node.id)
    layer_uri = node.layer.dataProvider().dataSourceUri()

    buffer = processing.run("native:buffer",
        {'INPUT':
            QgsProcessingFeatureSourceDefinition(
                layer_uri,
                selectedFeaturesOnly=True,
                featureLimit=-1, geometryCheck=QgsFeatureRequest.GeometryAbortOnInvalid),
        'DISTANCE':distance,
        'SEGMENTS':5,
        'END_CAP_STYLE':0,'JOIN_STYLE':0,'MITER_LIMIT':2,\
        'DISSOLVE':False,'OUTPUT':'memory:'})['OUTPUT']
    node.layer.removeSelection()
    #QgsProject.instance().addMapLayer(buffer)
    return buffer


#clips a layer to a buffer
def clip_layer(layer, overlay, name):
    clipped = processing.run("native:clip", \
        {'INPUT': layer, 'OVERLAY':overlay, \
        'OUTPUT': 'memory:'})['OUTPUT']
    clipped.setName(name)
    #QgsProject.instance().addMapLayer(clipped)
    return clipped


'''
def clone_layer(layer, name):
    layer.selectAll()
    clone_layer = processing.run("native:saveselectedfeatures", \
    {'INPUT': layer, 'OUTPUT': 'memory:'})['OUTPUT']
    layer.removeSelection()
    clone_layer.setName(name)
    return clone_layer
    #QgsProject.instance().addMapLayer(clone_layer)
'''


def create_reachable_stops_layer(stops_dict):
    stops_layer.removeSelection()
    stops_layer.selectByIds(list(stops_dict.keys()))
    clone_layer = processing.run("native:saveselectedfeatures", \
                                 {'INPUT': stops_layer, 'OUTPUT': 'memory:'})['OUTPUT']
    stops_layer.removeSelection()
    clone_layer.setName("Reachable_stops")
    QgsProject.instance().addMapLayer(clone_layer)
    return clone_layer


def remove_unreachable_stops(paths, start_time):
    unreachable = []
    for f in paths.getFeatures():
        if f['cost']:
            if start_time + f['cost'] > total_time:
                unreachable.append(f.id())
    paths.dataProvider().deleteFeatures(unreachable)
    paths.triggerRepaint()

def select_feature_by_attribute(layer, field_name, value):
    layer.removeSelection()
    processing.run("qgis:selectbyattribute", {
    'INPUT': layer,
    'FIELD': field_name, 'OPERATOR': 0,
    'VALUE': value, 'METHOD': 0})


def select_by_route(layer, rt_num, rt_dir):
    layer.removeSelection()
    exp_string = f' "rte" is {rt_num} and "dir" is {rt_dir}'
    processing.run("qgis:selectbyexpression", {
        'INPUT': layer,
        'EXPRESSION': exp_string, 'METHOD': 0})


def convert_features_to_list(layer):
    lst = []
    for feature in layer.getFeatures():
        attributes = feature.__geo_interface__["properties"]
        lst.append(attributes)
    return lst


'''
nearby_routes_to_stops = get_reachable_stops_walking(start_point_layer, total_time)
add_search_nodes(nearby_routes_to_stops, 'fid', transit_search, transit_search_nodes, total_time)

print("dictionary:")
print(transit_search_nodes)
print("sorted list:")
print(transit_search)
next = pick_next(transit_search, transit_search_nodes)
print(next)
'''