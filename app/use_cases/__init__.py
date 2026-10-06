"""Capa de lógica de negocio (Capa 2).

Orquesta los casos de uso y posee las reglas de dominio: el checksum es la
identidad del documento, ``text`` y ``checksum`` son inmutables, y un checksum
que ya existe nunca debe insertarse dos veces.

Regla de dependencias: este paquete llega a la persistencia sólo a través del
protocolo ``TextRepository`` declarado en :mod:`app.services.ports`, y nunca
debe importar ``pymongo``.
"""
