import 'dart:async';

import 'package:flutter/material.dart';

import 'bridge/bridge_client.dart';
import 'screens/main_content.dart';
import 'widgets/side_menu.dart';

class HackMateAction {
  final String id;
  final IconData icon;
  final String title;
  final String subtitle;

  const HackMateAction({
    required this.id,
    required this.icon,
    required this.title,
    required this.subtitle,
  });
}

const accentColors = [
  ('Green', Color(0xFF00E68A)),
  ('Blue', Color(0xFF4C8DFF)),
  ('Purple', Color(0xFFB388FF)),
  ('Orange', Color(0xFFFFA458)),
  ('Pink', Color(0xFFFF6FA5)),
];

const homeActions = [
  HackMateAction(
    id: 'build_efi',
    icon: Icons.construction_rounded,
    title: 'Build EFI',
    subtitle: 'Guided, automated EFI build',
  ),
  HackMateAction(
    id: 'build_efi_manual',
    icon: Icons.handyman_rounded,
    title: 'Build EFI (Manual)',
    subtitle: 'Step through each option yourself',
  ),
  HackMateAction(
    id: 'health_check',
    icon: Icons.health_and_safety_rounded,
    title: 'EFI Health Check',
    subtitle: 'Scan your current EFI',
  ),
  HackMateAction(
    id: 'restore_efi',
    icon: Icons.restore_rounded,
    title: 'Restore EFI',
    subtitle: 'Roll back to a backup',
  ),
  HackMateAction(
    id: 'download_recovery',
    icon: Icons.cloud_download_rounded,
    title: 'Download Recovery',
    subtitle: 'Fetch a recoveryOS image from Apple',
  ),
  HackMateAction(
    id: 'disk_map',
    icon: Icons.dns_rounded,
    title: 'Dual Boot / Disk Map',
    subtitle: 'View connected disks',
  ),
  HackMateAction(
    id: 'usb_mapping',
    icon: Icons.usb_rounded,
    title: 'USB Mapping',
    subtitle: 'Detect and label USB ports',
  ),
  HackMateAction(
    id: 'edit_config',
    icon: Icons.edit_note_rounded,
    title: 'Edit Config',
    subtitle: 'Open config.plist',
  ),
  HackMateAction(
    id: 'check_logs',
    icon: Icons.receipt_long_rounded,
    title: 'Check Logs',
    subtitle: 'Review the latest build output',
  ),
  HackMateAction(
    id: 'build_history',
    icon: Icons.history_rounded,
    title: 'Build History',
    subtitle: 'Browse previous builds',
  ),
  HackMateAction(
    id: 'offline_installer',
    icon: Icons.download_for_offline_rounded,
    title: 'Offline Installer',
    subtitle: 'Full macOS installer on a 2nd USB (UnPlugged)',
  ),
];

class HomeShell extends StatefulWidget {
  final BridgeClient bridge;
  final ThemeMode themeMode;
  final Color seedColor;
  final ValueChanged<ThemeMode> onThemeModeChanged;
  final ValueChanged<Color> onSeedColorChanged;

  const HomeShell({
    super.key,
    required this.bridge,
    required this.themeMode,
    required this.seedColor,
    required this.onThemeModeChanged,
    required this.onSeedColorChanged,
  });

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> {
  String _selectedId = 'welcome';
  bool _sharingLogs = true;

  @override
  void initState() {
    super.initState();
    widget.bridge.call('settings.get_log_sharing').then((result) {
      if (!mounted) return;
      setState(() => _sharingLogs = result['enabled'] == true);
    }).catchError((_) {});
  }

  void _select(String id) {
    setState(() => _selectedId = id);
  }

  Future<void> _setSharingLogs(bool v) async {
    setState(() => _sharingLogs = v);
    try {
      await widget.bridge.call('settings.set_log_sharing', {'enabled': v});
    } catch (e) {
      if (!mounted) return;
      setState(() => _sharingLogs = !v);
      ScaffoldMessenger.of(context).clearSnackBars();
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Could not update setting: $e')),
      );
    }
  }

  void _handleAction(String title) {
    ScaffoldMessenger.of(context).clearSnackBars();
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text('"$title", not wired up yet, just checking the look 👀'),
        duration: const Duration(seconds: 2),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;

    return Scaffold(
      body: Row(
        children: [
          SideMenu(
            bridge: widget.bridge,
            selectedId: _selectedId,
            actions: homeActions,
            sharingLogs: _sharingLogs,
            onSelect: _select,
            onSharingChanged: (v) => unawaited(_setSharingLogs(v)),
          ),
          Expanded(
            child: Container(
              color: scheme.surface,
              child: MainContent(
                bridge: widget.bridge,
                selectedId: _selectedId,
                actions: homeActions,
                onAction: _handleAction,
                themeMode: widget.themeMode,
                seedColor: widget.seedColor,
                onThemeModeChanged: widget.onThemeModeChanged,
                onSeedColorChanged: widget.onSeedColorChanged,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
