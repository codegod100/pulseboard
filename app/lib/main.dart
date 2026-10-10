import 'package:flutter/material.dart';

import 'src/app_state.dart';
import 'src/screens/home_shell.dart';
import 'src/theme.dart';

void main() {
  runApp(const PulseboardApp());
}

class PulseboardApp extends StatefulWidget {
  const PulseboardApp({super.key});

  @override
  State<PulseboardApp> createState() => _PulseboardAppState();
}

class _PulseboardAppState extends State<PulseboardApp> {
  final _state = AppState();

  @override
  void initState() {
    super.initState();
    // The feed list loads from the shell, which is the only screen that
    // needs it; there is no session to restore first.
  }

  @override
  void dispose() {
    _state.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AppScope(
      state: _state,
      child: MaterialApp(
        title: 'Pulseboard',
        debugShowCheckedModeBanner: false,
        theme: pulseboardTheme(Brightness.light),
        darkTheme: pulseboardTheme(Brightness.dark),
        builder: (context, child) => PulseboardKit(child: child!),
        home: const HomeShell(),
      ),
    );
  }
}
