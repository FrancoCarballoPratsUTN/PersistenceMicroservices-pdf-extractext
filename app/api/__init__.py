"""Capa de presentación (Capa 1).

Posee los asuntos HTTP en exclusiva: enrutado, autenticación por token bearer,
middleware, validación del body de la petición y serialización de problem
details RFC 9457.

Regla de dependencias: este paquete puede importar de :mod:`app.services`, y nunca
debe importar ``pymongo`` ni :mod:`app.repositories`. Los handlers reciben un
servicio ya construido por el cableado de inyección de :mod:`app.api.dependencies`.
"""
