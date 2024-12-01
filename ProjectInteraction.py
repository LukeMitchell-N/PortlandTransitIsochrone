import select
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
                       QgsPointXY,
                       QgsVectorFileWriter)
from qgis import processing

streets_name = '1HrWalkableRoads_NoHighways'
route_stops_name = 'trimet_route_stops'
stops_name = 'trimet_stops'
routes_name = 'trimet_routes'
blocks_name = 'census_blocks_land_only'

street_layer = QgsProject.instance().mapLayersByName(streets_name)[0]
route_stops_layer = QgsProject.instance().mapLayersByName(route_stops_name)[0]
stops_layer = QgsProject.instance().mapLayersByName(stops_name)[0]
routes_layer = QgsProject.instance().mapLayersByName(routes_name)[0]
blocks_layer = QgsProject.instance().mapLayersByName(blocks_name)[0]

walk_feet_per_hour = 14784  #feet walkable in one hour \
    #assuming a walking speed of 2.8 mph
walk_km_per_hour = 4.50616
ft_to_m = 3.28084



#finds the time to reach each stop within a street network
def find_stops_walking(start_node, network, stops, context, feedback):
    # get the coordinates as a string from the start node
    lat_lon_str = start_node.get_coord_string()

    # Note: due to this algorithm calculating distances on these layers in feet,
    #   we have to multiply the km/hr by ft_to_meters to get the correct times
    #print(f"FSW - network type: {type(network)}, feature count = {network.featureCount()}")
    #print(f"FSW - stops type: {type(stops)}, feature count = {stops.featureCount()}")
    #print(f"FSW - lat_lon_str: {lat_lon_str}")
    #print(f"FSW - default speed: {ft_to_m * walk_km_per_hour}")
    reachable_stops_id = processing.run("native:shortestpathpointtolayer",
                                     {'INPUT':network,'STRATEGY': 1,
                                      'DIRECTION_FIELD':'','VALUE_FORWARD':'',
                                      'VALUE_BACKWARD':'','VALUE_BOTH':'',
                                      'DEFAULT_DIRECTION':2,'SPEED_FIELD':'',
                                      'DEFAULT_SPEED': ft_to_m * walk_km_per_hour,
                                      'TOLERANCE':0,'START_POINT':lat_lon_str,
                                      'END_POINTS':stops, 'OUTPUT':'TEMPORARY_OUTPUT'},
                                    is_child_algorithm=True,
                                    context=context,
                                    feedback=feedback)['OUTPUT']
    reachable_stops = context.getMapLayer(reachable_stops_id)
    reachable_stops.setName(f"walking_routes from id {start_node.id}")
    #QgsProject.instance().addMapLayer(reachable_stops)
    return reachable_stops



def find_stops_transit(start_node, route, stops, context, feedback):
    # Select the starting stop by pulling it from the stops layer
    #start_stop = next(route_stops_layer.getFeatures(QgsFeatureRequest().setFilterFid(start_node.id)))

    # Get the starting coordinates as a string from the start node
    lat_lon_str = start_node.get_coord_string()

    # Get the path to the route and stops
    #   (Necessary for running this process with only selected features)
    #route_uri = route.dataProvider().dataSourceUri()
    #stops_uri = stops.dataProvider().dataSourceUri()

    direction = start_node.dir
    reverse = 1 if direction == 0 else 0
    routes_to_stops_id = processing.run("native:shortestpathpointtolayer",
                                     {'INPUT': route,
                                     'STRATEGY': 1, 'DIRECTION_FIELD': 'DIR', 'VALUE_FORWARD': direction,
                                     'VALUE_BACKWARD': reverse, 'VALUE_BOTH': '', 'DEFAULT_DIRECTION': direction,
                                     'SPEED_FIELD': 'KILO_FT_PER_HOUR', 'DEFAULT_SPEED': 1, 'TOLERANCE': 0,
                                     'START_POINT': lat_lon_str,
                                     'END_POINTS': stops,
                                    'OUTPUT': 'TEMPORARY_OUTPUT'},
                                    is_child_algorithm=True,
                                    context=context,
                                    feedback=feedback)['OUTPUT']
    routes_to_stops = context.getMapLayer(routes_to_stops_id)
    routes_to_stops.setName(f"transit_routes from id {start_node.id}")
    #QgsProject.instance().addMapLayer(routes_to_stops)
    return routes_to_stops



def get_reachable_stops_walking(start_node, time_limit, total_service_area, context, feedback):
    # Create buffer around start point with radius of
    # The maximum distance walkable with time remaining
    max_distance = walk_feet_per_hour * (time_limit - start_node.time)
    if start_node.is_search_origin:
        buffer = create_origin_buffer(start_node, max_distance, context, feedback)
    else:
        buffer = create_buffer(start_node, max_distance, context, feedback)

    if not buffer:
        print("No buffer, returning empty from get_reachable_stops_walking")
        return

    #QgsProject.instance().addMapLayer(buffer)

    # Clip the street layer to only search relevant streets
    nearby_streets = clip_layer(street_layer, buffer, "clipped streets", context, feedback)
    #QgsProject.instance().addMapLayer(nearby_streets)
    

    # Clip stop layer to only search relevant stops
    nearby_stops = clip_layer(route_stops_layer, buffer, "clipped stops", context, feedback)
    #QgsProject.instance().addMapLayer(nearby_stops)

    # Search the network to find all reachable stops
    search_routes = find_stops_walking(start_node, nearby_streets, nearby_stops, context, feedback)

    # Get rid of all stops that exceed the time remaining
    remove_unreachable_stops(search_routes, start_node.time, time_limit)

    # Get the walking service area from that node (not just the paths to nearby stops
    # but all street segments reachable from the node)
    local_service_area = create_walking_service_area(start_node, nearby_streets, time_limit, context, feedback)
    new_total_service_area = save_service_area(total_service_area, local_service_area, context, feedback)


    #QgsProject.instance().addMapLayer(search_routes)

    return search_routes, new_total_service_area



def get_reachable_stops_transit(start_node, time_limit, total_service_area, context, feedback):

    # Select the route and stops that match the start node's rte and dir
    isolated_route = extract_by_route(routes_layer, start_node.rte, start_node.dir, context, feedback)
    isolated_stops = extract_by_route(route_stops_layer, start_node.rte, start_node.dir, context, feedback)

    # Get the paths (portions of the route) from the start node to all stops on the route
    search_routes = find_stops_transit(start_node, isolated_route, isolated_stops, context, feedback)

    # Get rid of all stops that exceed the time remaining
    remove_unreachable_stops(search_routes, start_node.time, time_limit)

    new_total_service_area = save_service_area(total_service_area, search_routes, context, feedback)

    #QgsProject.instance().addMapLayer(search_routes)

    return search_routes, new_total_service_area



def create_walking_service_area(start_node, streets, total_time, context, feedback):
    lat_lon_str = start_node.get_coord_string()
    #print(f"CWSA - streets type: {type(streets)}, feature count = {streets.featureCount()}")
    service_area_id = processing.run("native:serviceareafrompoint", {
        'INPUT': streets,
        'STRATEGY': 1, 'DIRECTION_FIELD': '', 'VALUE_FORWARD': '', 'VALUE_BACKWARD': '', 'VALUE_BOTH': '',
        'DEFAULT_DIRECTION': 2, 'SPEED_FIELD': '', 'DEFAULT_SPEED': ft_to_m * walk_km_per_hour, 'TOLERANCE': 0,
        'START_POINT': lat_lon_str, 'TRAVEL_COST2': total_time - start_node.time, 'INCLUDE_BOUNDS': False,
        'OUTPUT_LINES': 'TEMPORARY_OUTPUT'},
        is_child_algorithm=True,
        context=context,
        feedback=feedback)['OUTPUT_LINES']
    service_area = context.getMapLayer(service_area_id)
    return service_area



def save_service_area(total_area, new_area, context, feedback):

    if total_area is None:
        total_area = new_area
    else:
        #print(f"SSA - total_area type: {type(total_area)}, feature count = {total_area.featureCount()}")
        #print(f"SSA - new_area type: {type(new_area)}, feature count = {new_area.featureCount()}")
        total_area_id = processing.run("native:mergevectorlayers", {
            'LAYERS': [total_area,
                       new_area], 'CRS': None,
            'OUTPUT': 'TEMPORARY_OUTPUT'},
            is_child_algorithm=True,
            context=context,
            feedback=feedback)['OUTPUT']
        total_area = context.getMapLayer(total_area_id)

        if total_area.featureCount() > 7:
            total_area = dissolve_layer(total_area, context, feedback)
    return total_area



# ********************************************************************************************************

# Create buffer around the point indicated by a node's layer and id
# Returns the vector layer containing the buffer
def create_buffer(node, distance, context, feedback):
    #print(f"   Creating buffer at coord {node.get_coord_string()} with distance {distance}")
    select_feature_by_attribute(node.layer, 'fid', node.id, context, feedback)
    node_extracted = extract_selection(node.layer, context, feedback)
    
    buffer_id = processing.run("native:buffer",
        {'INPUT': node_extracted,
        'DISTANCE':distance,
        'SEGMENTS':5,
        'END_CAP_STYLE':0,'JOIN_STYLE':0,'MITER_LIMIT':2,
        'DISSOLVE':False,'OUTPUT':'memory:'},
        is_child_algorithm=True,
        context=context,
        feedback=feedback)['OUTPUT']
    if not buffer_id or not context:
        return
    buffer = context.getMapLayer(buffer_id)
    node.layer.removeSelection()
    #QgsProject.instance().addMapLayer(buffer)
    return buffer


def create_origin_buffer(node, distance, context, feedback):
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

    #print(f"COB - layer type: {type(layer)}, feature count = {layer.featureCount()}")
    buffer_id = processing.run("native:buffer",
                            {'INPUT': layer,
                             'DISTANCE': distance,
                             'SEGMENTS': 5,
                             'END_CAP_STYLE': 0, 'JOIN_STYLE': 0, 'MITER_LIMIT': 2,
                             'DISSOLVE': False, 'OUTPUT': 'memory:'},
                            is_child_algorithm=True,
                            context=context,
                            feedback=feedback)['OUTPUT']
    buffer_output = context.getMapLayer(buffer_id)
    #QgsProject.instance().addMapLayer(buffer)
    #QgsProject.instance().addMapLayer(layer)
    return buffer_output


#clips a layer to a buffer
def clip_layer(layer, overlay, name, context, feedback):
    #print(f"CLIPLAYER - layer type: {type(layer)}, feature count = {layer.featureCount()}")
    #print(f"CLIPLAYER - overlay type: {type(overlay)}, feature count = {overlay.featureCount()}")
    #if overlay.featureCount() == 1:
        #feat = next(overlay.getFeatures())
        #print(feat)
        #print(feat.geometry())
    clipped_id = processing.run("native:clip",
                            {'INPUT': layer, 'OVERLAY':overlay,
                            'OUTPUT': 'memory:'},
                            is_child_algorithm=True,
                            context=context,
                            feedback=feedback)['OUTPUT']
    clipped = context.getMapLayer(clipped_id)
    clipped.setName(name)
    #QgsProject.instance().addMapLayer(clipped)
    return clipped


def dissolve_layer(layer, context, feedback):
    #print(f"DISSOLVE - layer type: {type(layer)}, feature count = {layer.featureCount()}")
    dissolved_id =  processing.run("native:dissolve", {
        'INPUT': layer, 'FIELD': [], 'SEPARATE_DISJOINT': False,
        'OUTPUT': 'TEMPORARY_OUTPUT'},
        is_child_algorithm=True,
        context=context,
        feedback=feedback)['OUTPUT']
    return context.getMapLayer(dissolved_id)


def polygonize(layer, context, feedback):
    #print(f"POLYGONIZE - layer type: {type(layer)}, feature count = {layer.featureCount()}")
    polygons_id = processing.run("native:polygonize",
                   {'INPUT':layer,'KEEP_FIELDS':False,
                    'OUTPUT':'TEMPORARY_OUTPUT'},
                    is_child_algorithm=True,
                    context=context,
                    feedback=feedback)['OUTPUT']
    polygons = context.getMapLayer(polygons_id)

    return dissolve_layer(polygons, context, feedback)

#return blocks within 10 ft of a feature
def get_nearby_blocks(feature, context, feedback):
    blocks_id = processing.run("native:extractwithindistance", 
                   {'INPUT':blocks_layer,
                    'REFERENCE':feature,'DISTANCE':10,
                    'OUTPUT':'TEMPORARY_OUTPUT'},
                    is_child_algorithm=True,
                    context=context,
                    feedback=feedback)['OUTPUT']
    return context.getMapLayer(blocks_id)


def add_layer(layer, name, group):
    layer.setName(name)
    QgsProject.instance().addMapLayer(layer, False)
    group.addLayer(layer)


def add_layer_to_gpkg(layer, name):
    layer.setName(name)
    file = r"C:\Users\lukem\Documents\Projects\PortlandTransitIsochrone\SkateparkOutput.gpkg"

    save_options = QgsVectorFileWriter.SaveVectorOptions()
    save_options.driverName = "GPKG"
    save_options.fileEncoding = "UTF-8"
    save_options.layerName = name
    save_options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer

    # get transform context from the project
    transform_context = QgsProject.instance().transformContext()
    
    # call writeAsVectorFormatV3() method, passing required arguments and
    # assign the return value to a variable
    error = QgsVectorFileWriter.writeAsVectorFormatV3(layer,
                                                      file,
                                                      transform_context,
                                                      save_options)

    if error[0] != QgsVectorFileWriter.NoError:
        print(error[1])
    else:
        print(f"{name} Exported Successfully!")


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


def create_reachable_stops_layer(stops_dict, context, feedback):
    stops_layer.removeSelection()
    stops_layer.selectByIds(list(stops_dict.keys()))
    #print(f"CRSL - stops_layer type: {type(stops_layer)}, feature count = {stops_layer.featureCount()}")
    clone_layer_id = processing.run("native:saveselectedfeatures",
                                 {'INPUT': stops_layer, 'OUTPUT': 'memory:'},
                                    is_child_algorithm=True,
                                    context=context,
                                    feedback=feedback)['OUTPUT']
    clone_layer = context.getMapLayer(clone_layer_id)
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

def select_feature_by_attribute(layer, field_name, value, context, feedback):
    layer.removeSelection()
    processing.run("qgis:selectbyattribute", {
    'INPUT': layer,
    'FIELD': field_name, 'OPERATOR': 0,
    'VALUE': value, 'METHOD': 0},
    is_child_algorithm=True,
    context=context,
    feedback=feedback)


def sort_paths_by_cost(paths):
    request = QgsFeatureRequest()

    # set order by field
    clause = QgsFeatureRequest.OrderByClause('cost', ascending=False)
    orderby = QgsFeatureRequest.OrderBy([clause])
    request.setOrderBy(orderby)
    sorted_paths = paths.getFeatures(request)

    return sorted_paths

def select_by_route(layer, rt_num, rt_dir, context, feedback):
    layer.removeSelection()
    exp_string = f' "rte" is {rt_num} and "dir" is {rt_dir}'
    processing.run("qgis:selectbyexpression", {
        'INPUT': layer,
        'EXPRESSION': exp_string, 'METHOD': 0},
        is_child_algorithm=True,
        context=context,
        feedback=feedback)

def extract_by_route(layer, rt_num, rt_dir, context, feedback):
    select_by_route(layer, rt_num, rt_dir, context, feedback)
    new_layer = extract_selection(layer, context, feedback)
    layer.removeSelection()
    return new_layer

def extract_selection(layer, context, feedback):
    new_layer = processing.run("native:saveselectedfeatures", 
                               {'INPUT':layer,
                               'OUTPUT':'TEMPORARY_OUTPUT'},
                               is_child_algorithm=True,
                               context=context,
                               feedback=feedback)['OUTPUT']
    return new_layer


def convert_features_to_list(layer):
    lst = []
    for feature in layer.getFeatures():
        attributes = feature.__geo_interface__["properties"]
        lst.append(attributes)
    return lst

