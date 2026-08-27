import 'package:flutter/material.dart';

import '../bridge/bridge_client.dart';

/// Stages a full macOS installer + corpnewt/UnPlugged on a second USB so the
/// install can run with no network. Does not replace the OpenCore USB.
class OfflineInstallerScreen extends StatefulWidget {
  final BridgeClient bridge;

  const OfflineInstallerScreen({super.key, required this.bridge});

  @override
  State<OfflineInstallerScreen> createState() => _OfflineInstallerScreenState();
}

class _OfflineInstallerScreenState extends State<OfflineInstallerScreen> {
  Future<void>? _loadFuture;
  List<dynamic> _versions = [];
  List<dynamic> _drives = [];
  String? _major;
  String? _device;

  bool _running = false;
  int _pct = 0;
  final List<String> _log = [];
  String? _resultMessage;
  bool _resultOk = true;

  @override
  void initState() {
    super.initState();
    _loadFuture = _load();
  }

  Future<void> _load() async {
    final vers = await widget.bridge.call('offline.supported_versions');
    final usb = await widget.bridge.call('usb.list_drives');
    if (!mounted) return;
    setState(() {
      _versions = vers['versions'] as List<dynamic>;
      _drives = usb['drives'] as List<dynamic>;
      _major = _versions.isNotEmpty ? _versions.first['major'] as String : null;
      _device = _drives.isNotEmpty ? _drives.first['device'] as String : null;
    });
  }

  Future<void> _refreshDrives() async {
    final usb = await widget.bridge.call('usb.list_drives');
    if (!mounted) return;
    setState(() {
      _drives = usb['drives'] as List<dynamic>;
      if (!_drives.any((d) => d['device'] == _device)) {
        _device = _drives.isNotEmpty ? _drives.first['device'] as String : null;
      }
    });
  }

  Future<void> _run() async {
    final major = _major;
    final device = _device;
    if (major == null || device == null) return;

    setState(() {
      _running = true;
      _pct = 0;
      _log.clear();
      _resultMessage = null;
    });
    try {
      final result = await widget.bridge.callStreaming(
        'offline.prepare',
        {'major': major, 'device': device},
        (event) {
          if (!mounted) return;
          final data = event.data as Map<String, dynamic>?;
          if (event.method == 'progress') {
            setState(() => _pct = (data?['pct'] as num?)?.toInt() ?? _pct);
          } else if (event.method == 'log') {
            final msg = data?['message']?.toString();
            if (msg != null && msg.isNotEmpty) setState(() => _log.add(msg));
          }
        },
      ) as Map<String, dynamic>;
      if (!mounted) return;
      final vol = result['volume']?.toString() ?? 'the USB';
      setState(() {
        _resultOk = true;
        _resultMessage =
            'Ready. On the target machine: boot the OpenCore USB, pick the '
            'recovery entry, open Utilities → Terminal, then run:\n\n'
            '    cd "$vol"\n    ./UnPlugged.command\n\n'
            '(see OFFLINE-INSTALL-README.txt on the USB)';
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _resultOk = false;
        _resultMessage = e is BridgeException ? e.message : e.toString();
      });
    } finally {
      if (mounted) setState(() => _running = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;

    return Padding(
      padding: const EdgeInsets.all(32),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 56,
                height: 56,
                decoration: BoxDecoration(
                  color: scheme.secondaryContainer,
                  borderRadius: BorderRadius.circular(20),
                ),
                child: Icon(Icons.download_for_offline_rounded,
                    size: 28, color: scheme.onSecondaryContainer),
              ),
              const SizedBox(width: 16),
              Text(
                'Offline Installer',
                style: Theme.of(context)
                    .textTheme
                    .headlineSmall
                    ?.copyWith(fontWeight: FontWeight.w700),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            'Downloads a full ~13 GB macOS installer and stages it plus '
            'UnPlugged.command onto a SECOND USB (16 GB+), so the install can '
            'run with no network. This does not replace the OpenCore USB — '
            'you still boot that, then run UnPlugged.command from this one. '
            'Beta: verify the staged files. github.com/corpnewt/UnPlugged',
            style: Theme.of(context).textTheme.bodyMedium,
          ),
          const SizedBox(height: 24),
          Expanded(
            child: FutureBuilder<void>(
              future: _loadFuture,
              builder: (context, snapshot) {
                if (snapshot.connectionState != ConnectionState.done) {
                  return const Center(child: CircularProgressIndicator());
                }
                if (snapshot.hasError) {
                  return Center(
                    child: Text(snapshot.error.toString(),
                        style: TextStyle(color: scheme.error)),
                  );
                }
                return SingleChildScrollView(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('macOS version',
                          style: Theme.of(context).textTheme.titleMedium),
                      const SizedBox(height: 8),
                      IgnorePointer(
                        ignoring: _running,
                        child: DropdownButtonFormField<String>(
                          initialValue: _major,
                          decoration: const InputDecoration(
                              border: OutlineInputBorder()),
                          items: [
                            for (final v in _versions)
                              DropdownMenuItem(
                                value: v['major'] as String,
                                child: Text(
                                    'macOS ${v['name']} (${v['major']})'),
                              ),
                          ],
                          onChanged: (value) =>
                              setState(() => _major = value),
                        ),
                      ),
                      const SizedBox(height: 16),
                      Row(
                        children: [
                          Text('Second USB (will be erased)',
                              style:
                                  Theme.of(context).textTheme.titleMedium),
                          const Spacer(),
                          TextButton.icon(
                            onPressed: _running ? null : _refreshDrives,
                            icon: const Icon(Icons.refresh_rounded, size: 18),
                            label: const Text('Refresh'),
                          ),
                        ],
                      ),
                      const SizedBox(height: 8),
                      IgnorePointer(
                        ignoring: _running,
                        child: DropdownButtonFormField<String>(
                          initialValue: _device,
                          decoration: const InputDecoration(
                              border: OutlineInputBorder(),
                              hintText: 'No USB drives detected'),
                          items: [
                            for (final d in _drives)
                              DropdownMenuItem(
                                value: d['device'] as String,
                                child: Text(
                                    '${d['device']}   ${d['size']}   ${d['label']}'),
                              ),
                          ],
                          onChanged: (value) =>
                              setState(() => _device = value),
                        ),
                      ),
                      const SizedBox(height: 20),
                      FilledButton.icon(
                        onPressed: (!_running &&
                                _major != null &&
                                _device != null)
                            ? _run
                            : null,
                        icon: const Icon(Icons.download_rounded),
                        label: const Text('Prepare offline USB'),
                      ),
                      if (_running) ...[
                        const SizedBox(height: 16),
                        LinearProgressIndicator(
                            value: _pct > 0 ? _pct / 100 : null),
                        const SizedBox(height: 6),
                        Text('$_pct%',
                            style: Theme.of(context).textTheme.bodySmall),
                      ],
                      if (_log.isNotEmpty) ...[
                        const SizedBox(height: 16),
                        Container(
                          padding: const EdgeInsets.all(12),
                          decoration: BoxDecoration(
                            color: scheme.surfaceContainerHigh,
                            borderRadius: BorderRadius.circular(12),
                          ),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              for (final line in _log) Text(line),
                            ],
                          ),
                        ),
                      ],
                      if (_resultMessage != null) ...[
                        const SizedBox(height: 16),
                        SelectableText(
                          _resultMessage!,
                          style: TextStyle(
                              color: _resultOk
                                  ? Colors.greenAccent
                                  : scheme.error),
                        ),
                      ],
                    ],
                  ),
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}
