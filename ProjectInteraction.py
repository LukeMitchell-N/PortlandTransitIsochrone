from qgis.core import (QgsProcessing,
                       QgsProcessingException,
                       QgsProcessingAlgorithm,
                       QgsFeature,
                       QgsProject, 
                       QgsProcessingFeatureSourceDefinition,
                       QgsFeatureRequest,
                       QgsExpression,
                       QgsVectorLayer,
                       QgsGeometry,
                       QgsPointXY)
from qgis import processing

streets_name = '1HrWalkableRoads_NoHighways'
route_stops_name = 'trimet_route_stops'
stops_name = 'trimet_stops'
routes_name = 'trimet_routes'

street_layer = QgsProject.instance().mapLayersByName(streets_name)[0]
route_stops_layer = QgsProject.instance().mapLayersByName(route_stops_name)[0]
stops_layer = QgsProject.instance().mapLayersByName(stops_name)[0]
routes_layer = QgsProject.instance().mapLayersByName(routes_name)[0]

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
    reachable_stops = processing.run("native:shortestpathpointtolayer",
        {'INPUT':network,'STRATEGY': 1,'DIRECTION_FIELD':'',
        'VALUE_FORWARD':'','VALUE_BACKWARD':'','VALUE_BOTH':'',
        'DEFAULT_DIRECTION':2,'SPEED_FIELD':'','DEFAULT_SPEED': ft_to_m * walk_km_per_hour,
        'TOLERANCE':0,'START_POINT':lat_lon_str,'END_POINTS':stops,
        'OUTPUT':'TEMPORARY_OUTPUT'})['OUTPUT']
    reachable_stops.setName(f"walking_routes from id {start_node.id}")
    #QgsProject.instance().addMapLayer(reachable_stops)
    return reachable_stops


def find_stops_transit(start_node, route, stops):
    # Select the starting stop by pulling it from the stops layer
    #start_stop = next(route_stops_layer.getFeatures(QgsFeatureRequest().setFilterFid(start_node.id)))

    # Get the starting coordinates as a string from the start node
    lat_lon_str = start_node.get_coord_string()

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
                                         'SPEED_FIELD': 'KILO_FT_PER_HOUR', 'DEFAULT_SPEED': 1, 'TOLERANCE': 0,
                                         'START_POINT': lat_lon_str,
                                         'END_POINTS': QgsProcessingFeatureSourceDefinition(
                                             stops_uri,
                                             selectedFeaturesOnly=True, featureLimit=-1,
                                             geometryCheck=QgsFeatureRequest.GeometryAbortOnInvalid),
                                         'OUTPUT': 'TEMPORARY_OUTPUT'})['OUTPUT']
    routes_to_stops.setName(f"transit_routes from id {start_node.id}")
    #QgsProject.instance().addMapLayer(routes_to_stops)
    return routes_to_stops


def get_reachable_stops_walking(start_node, time_limit, total_service_area):
    # Create buffer around start point with radius of
    # The maximum distance walkable with time remaining
    max_distance = walk_feet_per_hour * (time_limit - start_node.time)
    buffer = None
    if start_node.is_search_origin:
        buffer = create_origin_buffer(start_node, max_distance)
    else:
        buffer = create_buffer(start_node, max_distance)

    #QgsProject.instance().addMapLayer(buffer)

    # Clip the street layer to only search relevant streets
    nearby_streets = clip_layer(street_layer, buffer, "clipped streets")
    #QgsProject.instance().addMapLayer(nearby_streets)
    

    # Clip stop layer to only search relevant stops
    nearby_stops = clip_layer(route_stops_layer, buffer, "clipped stops")
    #QgsProject.instance().addMapLayer(nearby_stops)

    # Search the network to find all reachable stops
    search_routes = find_stops_walking(start_node, nearby_streets, nearby_stops)

    # Get rid of all stops that exceed the time remaining
    remove_unreachable_stops(search_routes, start_node.time, time_limit)

    # Get the walking service area from that node (not just the paths to nearby stops
    # but all street segments reachable from the node)
    local_service_area = create_walking_service_area(start_node, nearby_streets, time_limit)
    new_total_service_area = save_service_area(total_service_area, local_service_area)


    #QgsProject.instance().addMapLayer(search_routes)

    return search_routes, new_total_service_area

def get_reachable_stops_transit(start_node, time_limit, total_service_area):

    # Select the route and stops that match the start node's rte and dir
    select_by_route(routes_layer, start_node.rte, start_node.dir)
    select_by_route(route_stops_layer, start_node.rte, start_node.dir)

    # Get the paths (portions of the route) from the start node to all stops on the route
    search_routes = find_stops_transit(start_node, routes_layer, route_stops_layer)

    routes_layer.removeSelection()
    route_stops_layer.removeSelection()

    # Get rid of all stops that exceed the time remaining
    remove_unreachable_stops(search_routes, start_node.time, time_limit)

    new_total_service_area = save_service_area(total_service_area, search_routes)

    #QgsProject.instance().addMapLayer(search_routes)

    return search_routes, new_total_service_area


def create_walking_service_area(start_node, streets, total_time):
    lat_lon_str = start_node.get_coord_string()

    return processing.run("native:serviceareafrompoint", {
        'INPUT': streets,
        'STRATEGY': 1, 'DIRECTION_FIELD': '', 'VALUE_FORWARD': '', 'VALUE_BACKWARD': '', 'VALUE_BOTH': '',
        'DEFAULT_DIRECTION': 2, 'SPEED_FIELD': '', 'DEFAULT_SPEED': ft_to_m * walk_km_per_hour, 'TOLERANCE': 0,
        'START_POINT': lat_lon_str, 'TRAVEL_COST2': total_time - start_node.time, 'INCLUDE_BOUNDS': False,
        'OUTPUT_LINES': 'TEMPORARY_OUTPUT'})['OUTPUT_LINES']


def save_service_area(total_area, new_area):

    if total_area is None:
        total_area = new_area
    else:
        total_area = processing.run("native:mergevectorlayers", {
            'LAYERS': [total_area,
                       new_area], 'CRS': None,
            'OUTPUT': 'TEMPORARY_OUTPUT'})['OUTPUT']
        if total_area.featureCount() > 7:
            total_area = dissolve_layer(total_area)
    return total_area
    
    



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
        'END_CAP_STYLE':0,'JOIN_STYLE':0,'MITER_LIMIT':2,
        'DISSOLVE':False,'OUTPUT':'memory:'})['OUTPUT']
    node.layer.removeSelection()
    #QgsProject.instance().addMapLayer(buffer)
    return buffer


def create_origin_buffer(node, distance):
    coord = node.get_coord_string().split()[0]
    coord_lat = float(coord.split(',')[0])
    coord_lon = float(coord.split(',')[1])
    crs = node.get_coord_string().split()[1].split('[')[1]
    crs = crs.split(']')[0]

    url = "point?crs=" + crs
    layer = QgsVectorLayer(url, "init_point", "memory")

    feat = QgsFeature()
    feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(coord_lat, coord_lon)))
    provider = layer.dataProvider()
    provider.addFeatures([feat])

    buffer = processing.run("native:buffer",
                            {'INPUT': layer,
                             'DISTANCE': distance,
                             'SEGMENTS': 5,
                             'END_CAP_STYLE': 0, 'JOIN_STYLE': 0, 'MITER_LIMIT': 2,
                             'DISSOLVE': False, 'OUTPUT': 'memory:'})['OUTPUT']
    #QgsProject.instance().addMapLayer(buffer)
    #QgsProject.instance().addMapLayer(layer)
    return buffer


#clips a layer to a buffer
def clip_layer(layer, overlay, name):
    #clipped = processing.run("native:clip",
    #    {'INPUT': layer, 'OVERLAY':overlay,
    #    'OUTPUT': 'memory:'})['OUTPUT']
    clipped = processing.runalg("qgis:clip",layer,overlay,"memory:")['OUTPUT']
    clipped.setName(name)
    #QgsProject.instance().addMapLayer(clipped)
    return clipped


def dissolve_layer(layer):
    return processing.run("native:dissolve", {
        'INPUT': layer, 'FIELD': [], 'SEPARATE_DISJOINT': False,
        'OUTPUT': 'TEMPORARY_OUTPUT'})['OUTPUT']


def polygonize(layer):

    polygons = processing.run("native:polygonize",
                   {'INPUT':layer,'KEEP_FIELDS':False,
                    'OUTPUT':'TEMPORARY_OUTPUT'})['OUTPUT']

    return dissolve_layer(polygons)

def add_layer(layer):
    QgsProject.instance().addMapLayer(layer)
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
    clone_layer = processing.run("native:saveselectedfeatures",
                                 {'INPUT': stops_layer, 'OUTPUT': 'memory:'})['OUTPUT']
    stops_layer.removeSelection()
    clone_layer.setName("Reachable_stops")
    #QgsProject.instance().addMapLayer(clone_layer)
    return clone_layer


def remove_unreachable_stops(paths, start_time, total_time):
    unreachable = []
    for f in paths.getFeatures():
        if f['cost']:
            if start_time + f['cost'] > total_time:
                unreachable.append(f.id())
        else:
            unreachable.append(f.id())
    paths.dataProvider().deleteFeatures(unreachable)
    paths.triggerRepaint()

def select_feature_by_attribute(layer, field_name, value):
    layer.removeSelection()
    processing.run("qgis:selectbyattribute", {
    'INPUT': layer,
    'FIELD': field_name, 'OPERATOR': 0,
    'VALUE': value, 'METHOD': 0})


def sort_paths_by_cost(paths):
    request = QgsFeatureRequest()

    # set order by field
    clause = QgsFeatureRequest.OrderByClause('cost', ascending=False)
    orderby = QgsFeatureRequest.OrderBy([clause])
    request.setOrderBy(orderby)

    return paths.getFeatures(request)

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

