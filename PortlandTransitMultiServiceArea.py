from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (QgsProcessing,
                       QgsProcessingAlgorithm,
                       QgsProcessingException,
                        QgsProcessingParameterNumber,
                       QgsProcessingParameterVectorDestination,
                       QgsProcessingParameterFeatureSource,
                       QgsProcessingParameterField)
from importlib import reload
import ServiceAreaSearch
reload(ServiceAreaSearch)


class MultiTransitServiceArea(QgsProcessingAlgorithm):

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return MultiTransitServiceArea()

    def name(self):
        return 'multitransitservicearea'

    def displayName(self):
        return self.tr('Multi Transit Service Area')


    def shortHelpString(self):
        return self.tr('Generates accurate public transit service areas for all points in a point layer given a time limit')

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                'STARTLOCATIONS',
                self.tr('Vector Layer Representing Search Points'),
                [QgsProcessing.TypeVectorPoint]
            )
        )

        self.addParameter(
            QgsProcessingParameterField(
                'NAME_FIELD',
                self.tr('Location Name Field'),
                parentLayerParameterName='STARTLOCATIONS',
                optional=True,
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                'SEARCHTIMELIMIT',
                self.tr('Search Time Limit (Minutes)')
            )
        )

        self.addParameter(
            QgsProcessingParameterVectorDestination(
                'OUTPUT',
                self.tr('Output Location')
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        start_locations = self.parameterAsSource(parameters, 'STARTLOCATIONS', context)
        search_time = self.parameterAsInt(parameters, 'SEARCHTIMELIMIT', context) / 60
        name_field = parameters['NAME_FIELD']

        crs = start_locations.sourceCrs()
        points = start_locations.getFeatures()
        point_count = 0
        for point in points:
            if feedback.isCanceled():
                return {}

            reload(ServiceAreaSearch)
            name = point[name_field] if point[name_field] is not None else f"Point {point_count}"
            coord = point.geometry().asPoint()
            start_location = f"{coord.x()},{coord.y()} [{crs.authid()}]"

            ServiceAreaSearch.main(name, start_location, search_time, context, feedback)



        return {}