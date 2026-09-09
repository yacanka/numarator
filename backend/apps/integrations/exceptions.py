from rest_framework.exceptions import APIException


class Conflict(APIException):
    status_code = 409
    default_detail = 'The request conflicts with the current resource state.'
    default_code = 'conflict'


class GenerationFailed(APIException):
    status_code = 422
    default_detail = 'The number could not be generated with the supplied data.'
    default_code = 'generation_failed'
