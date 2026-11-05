#include "reader.h"

#include <QGuiApplication>
#include <QMetaMethod>
#include <QQmlApplicationEngine>

#ifdef __EMSCRIPTEN__
#include <emscripten/bind.h>

// Hooks for the browser test (test/e2e.cjs): read the state, and press the
// app's buttons by name.
static Reader *g_reader = nullptr;

static std::string pbSnapshot() {
    return g_reader ? g_reader->snapshot().toStdString() : std::string("null");
}

// pbCall("editFeed", [2, "Title", "https://…", ""]): a Reader method by name,
// with its arguments converted to the parameter types.
static void pbCall(const std::string &name, const emscripten::val &args) {
    if (!g_reader)
        return;
    const QMetaObject *mo = g_reader->metaObject();
    QList<QVariant> vals;
    if (args.isArray()) {
        const int n = args["length"].as<int>();
        for (int i = 0; i < n; ++i) {
            const emscripten::val a = args[i];
            vals << (a.typeOf().as<std::string>() == "number" ? QVariant(a.as<double>())
                                                              : QVariant(QString::fromStdString(a.as<std::string>())));
        }
    } else if (!args.isNull() && !args.isUndefined()) {
        vals << (args.typeOf().as<std::string>() == "number" ? QVariant(args.as<double>())
                                                             : QVariant(QString::fromStdString(args.as<std::string>())));
    }
    for (int m = mo->methodOffset(); m < mo->methodCount(); ++m) {
        const QMetaMethod mm = mo->method(m);
        if (mm.name() != QByteArray::fromStdString(name) || mm.parameterCount() != vals.size())
            continue;
        QGenericArgument a[4];
        for (int i = 0; i < vals.size() && i < 4; ++i) {
            vals[i].convert(mm.parameterMetaType(i));
            a[i] = QGenericArgument(mm.parameterMetaType(i).name(), vals[i].constData());
        }
        mm.invoke(g_reader, Qt::DirectConnection, a[0], a[1], a[2], a[3]);
        return;
    }
    qWarning("pbCall: no Reader method %s with %d arguments", name.c_str(), int(vals.size()));
}

EMSCRIPTEN_BINDINGS(pulseboard) {
    emscripten::function("pbSnapshot", &pbSnapshot);
    emscripten::function("pbCall", &pbCall);
}
#endif

int main(int argc, char *argv[]) {
    QGuiApplication app(argc, argv);
    app.setApplicationName("Pulseboard");

    QQmlApplicationEngine engine;
    QObject::connect(&engine, &QQmlApplicationEngine::objectCreationFailed, &app,
                     [] { QCoreApplication::exit(1); }, Qt::QueuedConnection);
    engine.loadFromModule("Pulseboard", "Main");
#ifdef __EMSCRIPTEN__
    g_reader = engine.singletonInstance<Reader *>("Pulseboard", "Reader");
#endif
    return app.exec();
}
