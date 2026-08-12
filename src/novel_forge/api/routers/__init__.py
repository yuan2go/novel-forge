"""PostgreSQL Authority API routers.

Production composition imports concrete router modules. Keeping this package
initializer side-effect free prevents migration and retired product surfaces
from becoming transitively reachable from the Authority API.
"""
