from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (QgsProcessing,
                       QgsProcessingAlgorithm,
                       QgsProcessingException,
                        QgsProcessingParameterNumber,
                       QgsProcessingParameterVectorDestination,
                       QgsProcessingParameterPoint)
from importlib import reload
import ServiceAreaSearch
reload(ServiceAreaSearch)


class PortlandTransitServiceArea(QgsProcessingAlgorithm):

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return PortlandTransitServiceArea()

    def name(self):
        return 'transitserviceareasearch'

    def displayName(self):
        return self.tr('Transit Service Area Search')


    def shortHelpString(self):
        return self.tr('Generates a public transit service area for any point in the Portland metropolitan area')

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterPoint(
                'STARTLOCATION',
                self.tr('Start Location'),
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
        start_location = self.parameterAsString(parameters, 'STARTLOCATION', context)
        search_time = self.parameterAsInt(parameters, 'SEARCHTIMELIMIT', context) / 60

        if feedback.isCanceled():
            return {}

        ServiceAreaSearch.main(start_location, search_time, feedback)

        return {}