# Pulseboard's web client: C++ and QML, built with Qt for WebAssembly.
# See build.sh, which drives this.
cmake_minimum_required(VERSION 3.21)
project(pulseboard LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(Qt6 6.8 REQUIRED COMPONENTS Core Gui Network Qml Quick)
qt_standard_project_setup(REQUIRES 6.8)

qt_add_executable(pulseboard
    src/main.cpp
    src/api.cpp src/api.h
    src/models.cpp src/models.h
    src/platform.cpp src/platform.h
    src/reader.cpp src/reader.h
)

set_source_files_properties(qml/Theme.qml PROPERTIES QT_QML_SINGLETON_TYPE TRUE)

qt_add_qml_module(pulseboard
    URI Pulseboard
    VERSION 1.0
    QML_FILES
        qml/Main.qml
        qml/Theme.qml
        qml/ReaderPage.qml
        qml/ManagePage.qml
        qml/ArticleRow.qml
        qml/Btn.qml
        qml/Field.qml
        qml/LabeledField.qml
        qml/Heading.qml
        qml/Icon.qml
        qml/Modal.qml
        qml/ScrollBar.qml
        qml/Spinner.qml
        qml/Tabs.qml
)

target_include_directories(pulseboard PRIVATE src)
target_link_libraries(pulseboard PRIVATE
    Qt6::Core Qt6::Gui Qt6::Network Qt6::Qml Qt6::Quick)

if(EMSCRIPTEN)
    target_link_options(pulseboard PRIVATE -lembind -sEXPORTED_RUNTIME_METHODS=UTF8ToString)
    # the 30 MB Qt default is far more than a feed reader needs
    set_target_properties(pulseboard PROPERTIES QT_WASM_INITIAL_MEMORY "50MB")
endif()
