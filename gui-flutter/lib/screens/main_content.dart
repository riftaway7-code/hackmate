import 'package:flutter/material.dart';

import '../bridge/bridge_client.dart';
import '../home_shell.dart';
import 'build_efi/wizard_flow.dart';
import 'build_history_screen.dart';
import 'config_editor_screen.dart';
import 'disk_map_screen.dart';
import 'efi_health_screen.dart';
import 'log_checker_screen.dart';
import 'offline_installer_screen.dart';
import 'recovery_download_screen.dart';
import 'restore_screen.dart';
import 'settings_screen.dart';
import 'usb_mapping_screen.dart';
import 'welcome_screen.dart';

class MainContent extends StatelessWidget {
  final BridgeClient bridge;
  final String selectedId;
  final List<HackMateAction> actions;
  final ValueChanged<String> onAction;
  final ThemeMode themeMode;
  final Color seedColor;
  final ValueChanged<ThemeMode> onThemeModeChanged;
  final ValueChanged<Color> onSeedColorChanged;

  const MainContent({
    super.key,
    required this.bridge,
    required this.selectedId,
    required this.actions,
    required this.onAction,
    required this.themeMode,
    required this.seedColor,
    required this.onThemeModeChanged,
    required this.onSeedColorChanged,
  });

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;

    switch (selectedId) {
      case 'welcome':
        return const WelcomePane();
      case 'settings':
        return SettingsPane(
          themeMode: themeMode,
          seedColor: seedColor,
          onThemeModeChanged: onThemeModeChanged,
          onSeedColorChanged: onSeedColorChanged,
        );
      case 'build_history':
        return BuildHistoryScreen(bridge: bridge);
      case 'check_logs':
        return LogCheckerScreen(bridge: bridge);
      case 'health_check':
        return EfiHealthScreen(bridge: bridge);
      case 'disk_map':
        return DiskMapScreen(bridge: bridge);
      case 'restore_efi':
        return RestoreScreen(bridge: bridge);
      case 'download_recovery':
        return RecoveryDownloadScreen(bridge: bridge);
      case 'offline_installer':
        return OfflineInstallerScreen(bridge: bridge);
      case 'usb_mapping':
        return UsbMappingScreen(bridge: bridge);
      case 'edit_config':
        return ConfigEditorScreen(bridge: bridge);
      case 'build_efi':
        return BuildEfiFlow(key: const ValueKey('build_efi_auto'), bridge: bridge, manual: false);
      case 'build_efi_manual':
        return BuildEfiFlow(key: const ValueKey('build_efi_manual'), bridge: bridge, manual: true);
    }

    final action = actions.firstWhere((a) => a.id == selectedId);

    return Center(
      child: Container(
        width: 72,
        height: 72,
        decoration: BoxDecoration(
          color: scheme.secondaryContainer,
          borderRadius: BorderRadius.circular(24),
        ),
        child: Icon(
          action.icon,
          size: 36,
          color: scheme.onSecondaryContainer,
        ),
      ),
    );
  }
}
