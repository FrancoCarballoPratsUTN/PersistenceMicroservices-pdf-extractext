"""Routers HTTP, un módulo por recurso.

Los handlers se mantienen finos: leen y validan la petición, delegan en el
servicio, y traducen el resultado a una respuesta. No contienen reglas de negocio.
"""
