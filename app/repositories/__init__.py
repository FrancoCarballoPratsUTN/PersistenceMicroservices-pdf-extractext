"""Capa de acceso a datos (Capa 3).

La única capa que sabe que MongoDB existe. Implementa el protocolo
``TextRepository`` declarado en :mod:`app.services.ports` y traduce las
excepciones del driver a los errores de dominio definidos en :mod:`app.errors`.

Regla de dependencias: este paquete puede importar de :mod:`app.errors`, y nunca
debe importar de :mod:`app.api` ni de tipos con comportamiento de
:mod:`app.services`. Lanza excepciones de dominio, nunca códigos de estado HTTP.
"""
