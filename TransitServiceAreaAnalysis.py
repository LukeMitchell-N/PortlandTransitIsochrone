from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (QgsProcessing,
                       QgsProcessingException,
                       QgsProcessingAlgorithm,
                       QgsFeature)
from qgis import processing

import time
from Search import *


point_name = 'start_point_test'
streets_name = '1HrWalkableRoads_NoHighways'
route_stops_name = 'trimet_route_stops'
stops_name = 'trimet_stops'
routes_name = 'TrimetRoutes_KPH'

start_point_layer = QgsProject.instance().mapLayersByName(point_name)[0]
street_layer = QgsProject.instance().mapLayersByName(streets_name)[0]
route_stops_layer = QgsProject.instance().mapLayersByName(route_stops_name)[0]
stops_layer = QgsProject.instance().mapLayersByName(stops_name)[0]
routes_layer = QgsProject.instance().mapLayersByName(routes_name)[0]



total_time = .5
time_remaining = .5
hour_walk_feet = 14784  #feet walkable in one hour \
    #assuming a walking speed of 2.8 mph

#create buffer around a given point
#returns the vector layer containing the buffer
def create_walk_buffer(point, distance):
    buffer = processing.run("native:buffer", 
        {'INPUT':point,'DISTANCE':distance,'SEGMENTS':5,\
        'END_CAP_STYLE':0,'JOIN_STYLE':0,'MITER_LIMIT':2,\
        'DISSOLVE':False,'OUTPUT':'memory:'})['OUTPUT']
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

# Hard-coding using route_stop_layer's CRS, may need to change
def get_coord_string(point): return f"{point.x()},{point.y()} [{route_stops_layer.crs().authid()}]"

#finds the time to reach each stop within a street network
def find_stops(start, network, stops):
    lat_lon_str = get_coord_string(start.getFeature(0).geometry().asPoint())

    reachable_stops = processing.run("native:shortestpathpointtolayer", \
        {'INPUT':network,'STRATEGY':1,'DIRECTION_FIELD':'',\
        'VALUE_FORWARD':'','VALUE_BACKWARD':'','VALUE_BOTH':'',\
        'DEFAULT_DIRECTION':2,'SPEED_FIELD':'','DEFAULT_SPEED':4.50616,\
        'TOLERANCE':0,'START_POINT':lat_lon_str,'END_POINTS':stops,\
        'OUTPUT':'TEMPORARY_OUTPUT'})['OUTPUT']
    reachable_stops.setName("walking_routes")
    #QgsProject.instance().addMapLayer(reachable_stops)
    return reachable_stops


def find_stops_transit(start_fid, dir, route, stops, time):
    #select the starting stop by pulling it from the stops layer
    start_stop = next(stops.getFeatures(QgsFeatureRequest().setFilterFid(start_fid)))

    #get the coordinates as a string from the start point
    lat_lon_str = get_coord_string(start_stop.geometry().asPoint())

    route_uri = route.dataProvider().dataSourceUri()
    stops_uri = stops.dataProvider().dataSourceUri()
    routes_to_stops = processing.run("native:shortestpathpointtolayer",
                                     {'INPUT': QgsProcessingFeatureSourceDefinition(
                                         route_uri,
                                         selectedFeaturesOnly=True, featureLimit=-1,
                                         geometryCheck=QgsFeatureRequest.GeometryAbortOnInvalid),
                                         'STRATEGY': 1, 'DIRECTION_FIELD': 'DIR', 'VALUE_FORWARD': dir,
                                         'VALUE_BACKWARD': '0', 'VALUE_BOTH': '', 'DEFAULT_DIRECTION': 0,
                                         'SPEED_FIELD': 'AVG_KPH', 'DEFAULT_SPEED': 50, 'TOLERANCE': 0,
                                         'START_POINT': lat_lon_str,
                                         'END_POINTS': QgsProcessingFeatureSourceDefinition(
                                             stops_uri,
                                             selectedFeaturesOnly=True, featureLimit=-1,
                                             geometryCheck=QgsFeatureRequest.GeometryAbortOnInvalid),
                                         'OUTPUT': 'TEMPORARY_OUTPUT'})['OUTPUT']
    routes_to_stops.setName("transit_routes")
    QgsProject.instance().addMapLayer(routes_to_stops)
    return routes_to_stops

def get_reachable_stops_walking(start, time):
    #create buffer around start point with radius of 
    #maximum distance walkable with time remaining
    max_distance = hour_walk_feet * time
    buffer = create_walk_buffer(start, max_distance)
    
    #clip the street layer to only search relevant streets
    potential_streets = clip_layer(street_layer, buffer, "clipped streets")
    
    #clip stop layer to only search relevant stops
    potential_stops = clip_layer(route_stops_layer, buffer, "clipped stops")
    
    #search the network to find all reachable stops
    return find_stops(start_point_layer, potential_streets, potential_stops)




def get_reachable_stops_transit(s_start, time):

    #select the route and stops that match the start node's rte and dir
    select_by_route(routes_layer, s_start.rte, s_start.dir)
    select_by_route(route_stops_layer, s_start.rte, s_start.dir)

    find_stops_transit(s_start.id, s_start.dir, routes_layer, route_stops_layer, time)



# Selects(modifies) the stop from the route_stops layer
#
def select_stop_by_fid(layer, fid):
    return processing.run("qgis:selectbyattribute", {
        'INPUT': layer,
        'FIELD': 'fid', 'OPERATOR': 0,
        'VALUE': fid, 'METHOD': 0})['OUTPUT']

def select_by_route(layer, rt_num, rt_dir):
    layer.removeSelection()
    exp_string = f' "rte" is {rt_num} and "dir" is {rt_dir}'
    processing.run("qgis:selectbyexpression", {
        'INPUT': layer,
        'EXPRESSION': exp_string, 'METHOD': 0})


#
def sort_paths_by_cost(stops):
    request = qgis.core.QgsFeatureRequest()

    # set order by field
    clause = qgis.core.QgsFeatureRequest.OrderByClause('cost', ascending=False)
    orderby = qgis.core.QgsFeatureRequest.OrderBy([clause])
    request.setOrderBy(orderby)

    return stops.getFeatures(request)

def clone_layer(layer, name):
    layer.selectAll()
    clone_layer = processing.run("native:saveselectedfeatures", \
    {'INPUT': layer, 'OUTPUT': 'memory:'})['OUTPUT']
    layer.removeSelection()
    clone_layer.setName(name)
    return clone_layer
    #QgsProject.instance().addMapLayer(clone_layer)

def convert_features_to_list(layer):
    lst = []
    for feature in layer.getFeatures():
        attributes = feature.__geo_interface__["properties"]
        lst.append(attributes)
    return lst


#
start = SearchStart(3570,1)
start.set_route_dir(38,1)
get_reachable_stops_transit(start, 1)


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