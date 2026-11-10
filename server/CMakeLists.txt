# The Pulseboard server as one WASI component (wasi:http/proxy), built by
# qt2wasm from nandi.uk/qt2wasm:
#   qt2wasm build server --wit server/wit --world server -o pulseboard-server.wasm
# See server/README.md.
cmake_minimum_required(VERSION 3.21)
project(pulseboard_server C CXX)
# Lets clangd (and other IDEs) find Qt/WASI headers: it reads compile_commands.json
# for include paths, defines and the wasi_compat forced-include. The qt2wasm build
# itself does not need it, but the compile database is what keeps the editor from
# reporting "'QString' file not found" on every translation unit.
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
include(${QT2WASM_ROOT}/cmake/Qt2Wasm.cmake)

# The Postgres migrations, compiled in: migrations/*.sql -> migrations.inc.
file(GLOB _migrations "${CMAKE_CURRENT_SOURCE_DIR}/migrations/*.sql")
list(SORT _migrations)
set(_inc "struct Migration { const char *name; const char *sql; };\nstatic const Migration kMigrations[] = {\n")
foreach(_m ${_migrations})
    get_filename_component(_name "${_m}" NAME)
    file(READ "${_m}" _sql)
    string(APPEND _inc "    {\"${_name}\", R\"PBSQL(${_sql})PBSQL\"},\n")
endforeach()
string(APPEND _inc "};\n")
file(WRITE "${CMAKE_CURRENT_BINARY_DIR}/gen/migrations.inc" "${_inc}")
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS ${_migrations})

file(GLOB _sources "${CMAKE_CURRENT_SOURCE_DIR}/src/*.cpp")
qt2wasm_add_component(pulseboard_server
    SOURCES ${_sources} "${CMAKE_CURRENT_SOURCE_DIR}/src/3rdparty/p256-m/p256-m.c"
    INCLUDE_DIRS "${CMAKE_CURRENT_BINARY_DIR}/gen" "${CMAKE_CURRENT_SOURCE_DIR}/src"
                 "${CMAKE_CURRENT_SOURCE_DIR}/src/3rdparty/p256-m")
