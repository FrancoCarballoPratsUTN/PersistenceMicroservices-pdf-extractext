"""Configuración compartida de pytest para toda la suite.

La disposición de los tests refleja la de ``app/`` para que un test fallido
señale al módulo que cubre.

Convenciones
------------
* **Prevalece el test pequeño.** La lógica pura (validadores, serialización,
  mapeo de errores) se prueba de forma unitaria sin E/S. Solo el repositorio y
  los endpoints cruzan un límite real.
* **Fakes antes que mocks.** El dominio depende del protocolo ``TextRepository``,
  así que los tests unitarios sustituyen
  :class:`tests.fakes.fake_text_repository.FakeTextRepository` en lugar de simular
  secuencias de llamadas. Las aserciones apuntan al estado devuelto, no a qué
  métodos se llamaron.
* **DAMP antes que DRY.** Un test debe leerse como una especificación completa por
  sí mismo; el setup compartido solo compensa cuando no oculta ningún
  comportamiento.

Todavía no hay fixtures aquí. Las fixtures entre capas irán apareciendo aquí a
medida que se construyan las capas de las que dependen; las fixtures propias de
una capa se quedan en el ``conftest.py`` más cercano, para que su alcance sea
evidente.
"""
