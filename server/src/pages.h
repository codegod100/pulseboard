// The sign-in pages, which the server renders itself.
#pragma once

#include <QString>

namespace pages {

QString loginPage(const QString &identity = {}, const QString &error = {});
QString retryPage();

}  // namespace pages
