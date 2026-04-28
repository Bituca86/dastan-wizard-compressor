// ╔══════════════════════════════════════════════════════════╗
// ║  DASTAN WIZARD — Video Compressor Android               ║
// ║  Flutter + ffmpeg_kit_flutter · v1.0                    ║
// ║  by DastanWizard  ✦                                      ║
// ╚══════════════════════════════════════════════════════════╝

import 'dart:io';
import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:file_picker/file_picker.dart';
import 'package:ffmpeg_kit_flutter_full_gpl/ffmpeg_kit.dart';
import 'package:ffmpeg_kit_flutter_full_gpl/ffprobe_kit.dart';
import 'package:ffmpeg_kit_flutter_full_gpl/return_code.dart';
import 'package:path_provider/path_provider.dart';
import 'package:path/path.dart' as p;
import 'package:share_plus/share_plus.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:google_fonts/google_fonts.dart';

// ── Palette ──────────────────────────────────────────────────────────────────
const cBg     = Color(0xFF090910);
const cSurf   = Color(0xFF13131e);
const cCard   = Color(0xFF191928);
const cBorder = Color(0xFF222235);
const cTeal   = Color(0xFF00d4aa);
const cBlue   = Color(0xFF4a7cff);
const cOrange = Color(0xFFff6b35);
const cText   = Color(0xFFc0c0d8);
const cMuted  = Color(0xFF44445a);
const cGreen  = Color(0xFF22c55e);
const cWarn   = Color(0xFFf59e0b);
const cDanger = Color(0xFFef4444);

// ── Models ────────────────────────────────────────────────────────────────────
enum JobStatus { queued, processing, done, error }

class VideoJob {
  final String id;
  final String path;
  final String name;
  final int    size;
  double duration   = 0;
  String dims       = '';
  String inputCodec = '';
  JobStatus status  = JobStatus.queued;
  String? outputPath;
  int    outputSize = 0;
  double progress   = 0;
  String speed      = '';
  String fps        = '';
  String? ssim;
  String? errorMsg;

  VideoJob({required this.path, required this.name, required this.size})
    : id = '${DateTime.now().microsecondsSinceEpoch}_${name.hashCode.abs()}';

  String get savedPct {
    if (outputSize <= 0 || size <= 0) return '0%';
    return '${((size - outputSize) / size * 100).toStringAsFixed(1)}%';
  }

  String get ratioStr {
    if (outputSize <= 0 || size <= 0) return '—';
    return '${(size / outputSize).toStringAsFixed(2)}×';
  }

  double get savedNum => outputSize > 0 && size > 0
    ? (size - outputSize) / size * 100.0
    : 0.0;
}

// ═══════════════════════════════════════════════════════════════════════════════
//  MAIN
// ═══════════════════════════════════════════════════════════════════════════════
void main() {
  WidgetsFlutterBinding.ensureInitialized();
  SystemChrome.setSystemUIOverlayStyle(const SystemUiOverlayStyle(
    statusBarColor: cBg,
    statusBarIconBrightness: Brightness.light,
    systemNavigationBarColor: cBg,
    systemNavigationBarIconBrightness: Brightness.light,
  ));
  runApp(const DastanApp());
}

class DastanApp extends StatelessWidget {
  const DastanApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: '◈ Dastan Wizard',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        scaffoldBackgroundColor: cBg,
        colorScheme: ColorScheme.fromSeed(
          seedColor: cTeal,
          brightness: Brightness.dark,
          surface: cSurf,
        ),
        useMaterial3: true,
        sliderTheme: SliderThemeData(
          activeTrackColor: cTeal,
          inactiveTrackColor: cBorder,
          thumbColor: cTeal,
          overlayColor: cTeal.withOpacity(0.2),
          valueIndicatorColor: cTeal,
          valueIndicatorTextStyle: GoogleFonts.jetBrainsMono(
            color: Colors.black, fontSize: 12, fontWeight: FontWeight.bold),
        ),
      ),
      home: const HomeScreen(),
    );
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
//  HOME SCREEN
// ═══════════════════════════════════════════════════════════════════════════════
class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});
  @override
  State<HomeScreen> createState() => _HomeState();
}

class _HomeState extends State<HomeScreen> with SingleTickerProviderStateMixin {
  final List<VideoJob> _queue = [];
  bool _working  = false;
  bool _webOn    = true;
  bool _ssimOn   = true;
  final List<String> _log = [];

  // Settings
  String _codec   = 'h265';
  String _preset  = 'medium';
  double _crf     = 23;
  String _abr     = '128k';
  String _format  = 'mp4';

  final _scrollCtrl = ScrollController();

  // ── Codec quality label ──
  String get _crfLabel {
    if (_crf <= 22) return 'EXCELLENT — NEAR-LOSSLESS';
    if (_crf <= 28) return 'GREAT — RECOMANDAT';
    if (_crf <= 33) return 'GOOD — WEB / SOCIAL';
    return 'ACCEPTABLE — MAX COMPRESIE';
  }

  Color get _crfColor {
    if (_crf <= 22) return cGreen;
    if (_crf <= 28) return cWarn;
    if (_crf <= 33) return cOrange;
    return cDanger;
  }

  // ── Log ──
  void _log_(String msg) {
    final ts = TimeOfDay.now().format(context);
    setState(() => _log.add('[$ts] $msg'));
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollCtrl.hasClients) {
        _scrollCtrl.animateTo(
          _scrollCtrl.position.maxScrollExtent,
          duration: const Duration(milliseconds: 200),
          curve: Curves.easeOut,
        );
      }
    });
  }

  // ── Pick files ──
  Future<void> _pickFiles() async {
    // Request permissions
    final perm = Platform.isAndroid
      ? await Permission.videos.request()
      : PermissionStatus.granted;

    if (perm.isDenied) {
      // Try older permission for Android < 13
      await Permission.storage.request();
    }

    final result = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['mp4','mkv','mov','avi','wmv','webm','flv','m4v','3gp','ts'],
      allowMultiple: true,
    );

    if (result == null) return;

    for (final f in result.files) {
      if (f.path == null) continue;
      final job = VideoJob(
        path: f.path!,
        name: f.name,
        size: f.size,
      );
      setState(() => _queue.add(job));
      _probeVideo(job);
      _log_('Adăugat: ${f.name} (${_fmtSize(f.size)})');
    }
  }

  // ── Probe video metadata ──
  Future<void> _probeVideo(VideoJob job) async {
    final session = await FFprobeKit.getMediaInformation(job.path);
    final info = session.getMediaInformation();
    if (info == null) return;

    double dur = double.tryParse(info.getDuration() ?? '0') ?? 0;
    String dims = '', codec = '';

    for (final s in info.getStreams() ?? []) {
      if (s.getType() == 'video') {
        final w = s.getWidth() ?? 0;
        final h = s.getHeight() ?? 0;
        if (w > 0 && h > 0) dims = '${w}×${h}';
        codec = s.getCodec() ?? '';
        break;
      }
    }

    if (!mounted) return;
    setState(() {
      job.duration   = dur;
      job.dims       = dims;
      job.inputCodec = codec;
    });
  }

  // ── Remove file ──
  void _removeFile(VideoJob job) {
    if (_working && job.status == JobStatus.processing) return;
    setState(() => _queue.remove(job));
  }

  // ── Compress all ──
  Future<void> _compressAll() async {
    final pend = _queue.where((j) => j.status == JobStatus.queued).toList();
    if (pend.isEmpty || _working) return;

    setState(() => _working = true);
    _log_('━━ BATCH START: ${pend.length} fișier(e) ━━');
    _log_('Codec:${_codec.toUpperCase()} · CRF:${_crf.round()} · Preset:$_preset');

    for (final job in pend) {
      await _compressOne(job);
    }

    final done = _queue.where((j) => j.status == JobStatus.done).length;
    _log_('━━ BATCH GATA: $done/${pend.length} ✓ ━━');
    setState(() => _working = false);
  }

  // ── Compress single file ──
  Future<void> _compressOne(VideoJob job) async {
    setState(() {
      job.status   = JobStatus.processing;
      job.progress = 0;
    });
    _log_('⚡ Procesez: ${job.name}');

    try {
      final dir = await getTemporaryDirectory();
      final ts  = DateTime.now().millisecondsSinceEpoch;
      final ext = _format;
      final outPath = p.join(dir.path, 'DW_${ts}_${job.name.replaceAll(RegExp(r'[^a-zA-Z0-9]'), '_')}.$ext');

      final cmd = _buildCmd(job.path, outPath);
      _log_('  → ffmpeg ${cmd.substring(cmd.length > 80 ? cmd.length - 80 : 0)}...');

      // Duration for progress calculation
      final totalMs = job.duration * 1000;

      final completer = Completer<void>();
      final session = await FFmpegKit.executeAsync(
        cmd,
        // Completion callback
        (s) async {
          final rc = await s.getReturnCode();
          if (ReturnCode.isSuccess(rc)) {
            completer.complete();
          } else {
            final logs = await s.getLogs();
            final errMsg = logs.map((l) => l.getMessage()).join('\n');
            completer.completeError(errMsg);
          }
        },
        // Log callback
        null,
        // Statistics callback
        (stats) {
          if (!mounted) return;
          final currentMs = stats.getTime().toDouble();
          double pct = totalMs > 0 ? (currentMs / totalMs * 100).clamp(0, 99) : 0;
          setState(() {
            job.progress = pct;
            job.speed    = stats.getSpeed()?.toStringAsFixed(2) ?? '';
            job.fps      = stats.getVideoFps().toStringAsFixed(0);
          });
        },
      );

      await completer.future;

      final outFile = File(outPath);
      if (!await outFile.exists()) throw Exception('Output file not created');

      final outSize = await outFile.length();

      // SSIM analysis
      String? ssimVal;
      if (_ssimOn) {
        _log_('  Analiză SSIM...');
        setState(() => job.progress = 99.5);
        ssimVal = await _runSsim(job.path, outPath);
      }

      setState(() {
        job.status     = JobStatus.done;
        job.outputPath = outPath;
        job.outputSize = outSize;
        job.progress   = 100;
        job.ssim       = ssimVal;
      });

      _log_('  ✓ ${_fmtSize(job.size)} → ${_fmtSize(outSize)} · ${job.savedPct} economisit · ${job.ratioStr}${ssimVal != null ? ' · SSIM:$ssimVal' : ''}');

    } catch (e) {
      setState(() {
        job.status   = JobStatus.error;
        job.errorMsg = e.toString();
      });
      _log_('  ✗ Eroare: $e');
      await FFmpegKit.cancel();
    }
  }

  // ── Build FFmpeg command ──
  String _buildCmd(String input, String output) {
    final crf = _crf.round();
    final List<String> parts = ['-i', '"$input"'];

    if (_codec == 'h264') {
      parts.addAll(['-c:v', 'libx264', '-crf', '$crf', '-preset', _preset]);
      parts.addAll(['-c:a', 'aac', '-b:a', _abr]);
      if (_webOn) parts.addAll(['-movflags', '+faststart']);

    } else if (_codec == 'h265') {
      parts.addAll(['-c:v', 'libx265', '-crf', '$crf', '-preset', _preset, '-tag:v', 'hvc1']);
      parts.addAll(['-c:a', 'aac', '-b:a', _abr]);
      if (_webOn) parts.addAll(['-movflags', '+faststart']);

    } else if (_codec == 'vp9') {
      const cpuMap = {'ultrafast':5,'superfast':5,'veryfast':4,'faster':4,'fast':3,'medium':2,'slow':1,'slower':0};
      final cpu = cpuMap[_preset] ?? 2;
      final vp9Crf = (crf * 1.55).round().clamp(0, 63);
      parts.addAll(['-c:v', 'libvpx-vp9', '-crf', '$vp9Crf', '-b:v', '0',
                    '-cpu-used', '$cpu', '-row-mt', '1']);
      parts.addAll(['-c:a', 'libopus', '-b:a', _abr]);
    }

    parts.add('"$output"');
    return parts.join(' ');
  }

  // ── SSIM analysis ──
  Future<String?> _runSsim(String input, String output) async {
    try {
      final session = await FFmpegKit.execute(
        '-i "$input" -i "$output" -filter_complex "[0:v][1:v]ssim" -f null -'
      );
      final logs = await session.getLogs();
      for (final log in logs) {
        final m = RegExp(r'All:([0-9.]+)').firstMatch(log.getMessage() ?? '');
        if (m != null) return double.parse(m.group(1)!).toStringAsFixed(5);
      }
    } catch (_) {}
    return null;
  }

  // ── Share / Save ──
  Future<void> _shareFile(VideoJob job) async {
    if (job.outputPath == null) return;
    final base = p.basenameWithoutExtension(job.name);
    final name = '${base}_DW_crf${_crf.round()}_${_codec}.${_format}';
    await Share.shareXFiles(
      [XFile(job.outputPath!, name: name)],
      subject: 'Dastan Wizard — Video Comprimat',
    );
  }

  // ── Clear queue ──
  void _clearQueue() {
    if (_working) return;
    setState(() => _queue.clear());
  }

  @override
  Widget build(BuildContext context) {
    final hasPending = _queue.any((j) => j.status == JobStatus.queued);

    return Scaffold(
      backgroundColor: cBg,
      body: SafeArea(
        child: Column(
          children: [
            // ── Header ──────────────────────────────────────────
            _buildHeader(),

            Expanded(
              child: SingleChildScrollView(
                padding: const EdgeInsets.fromLTRB(14, 0, 14, 14),
                child: Column(
                  children: [
                    const SizedBox(height: 4),
                    // ── Pick files area ──
                    _buildPickArea(),
                    const SizedBox(height: 14),
                    // ── Settings ──
                    _buildSettings(),
                    const SizedBox(height: 10),
                    // ── Toggles ──
                    _buildToggle('🌐 Web-Stream Optimizat (faststart)',
                      'Moov atom la început · Video se redă instant în browser',
                      _webOn, (v) => setState(() => _webOn = v)),
                    const SizedBox(height: 8),
                    _buildToggle('📊 Analiză Calitate (SSIM)',
                      'Măsoară pierderea exactă de calitate (durată mai mare)',
                      _ssimOn, (v) => setState(() => _ssimOn = v)),
                    const SizedBox(height: 14),
                    // ── Queue ──
                    _buildQueueHeader(),
                    const SizedBox(height: 8),
                    _buildQueue(),
                    const SizedBox(height: 14),
                    // ── Action buttons ──
                    _buildActions(hasPending),
                    const SizedBox(height: 14),
                    // ── Console ──
                    _buildConsole(),
                    const SizedBox(height: 20),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  // ── Header ───────────────────────────────────────────────────────────────
  Widget _buildHeader() {
    return Container(
      padding: const EdgeInsets.fromLTRB(14, 14, 14, 14),
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: cBorder)),
      ),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                ShaderMask(
                  shaderCallback: (b) => const LinearGradient(
                    colors: [cTeal, cBlue],
                    begin: Alignment.centerLeft,
                    end: Alignment.centerRight,
                  ).createShader(b),
                  child: Text('◈ DASTAN WIZARD',
                    style: GoogleFonts.orbitron(
                      fontSize: 18, fontWeight: FontWeight.w900,
                      letterSpacing: 1.5, color: Colors.white)),
                ),
                const SizedBox(height: 2),
                Text('VIDEO COMPRESSOR · ANDROID · FFmpeg',
                  style: GoogleFonts.jetBrainsMono(
                    fontSize: 9, color: cMuted, letterSpacing: 2.5)),
              ],
            ),
          ),
          // Status chip
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 5),
            decoration: BoxDecoration(
              color: cSurf,
              borderRadius: BorderRadius.circular(20),
              border: Border.all(color: _working ? cTeal.withOpacity(0.4) : cGreen.withOpacity(0.4)),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Container(
                  width: 7, height: 7,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: _working ? cTeal : cGreen,
                    boxShadow: [BoxShadow(
                      color: (_working ? cTeal : cGreen).withOpacity(0.6),
                      blurRadius: 6,
                    )],
                  ),
                ),
                const SizedBox(width: 7),
                Text(_working ? 'COMPRESÂND' : 'READY',
                  style: GoogleFonts.jetBrainsMono(
                    fontSize: 10, color: _working ? cTeal : cGreen,
                    letterSpacing: 0.8)),
              ],
            ),
          ),
        ],
      ),
    );
  }

  // ── Pick area ─────────────────────────────────────────────────────────────
  Widget _buildPickArea() {
    return GestureDetector(
      onTap: _pickFiles,
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.symmetric(vertical: 32, horizontal: 20),
        decoration: BoxDecoration(
          color: cSurf,
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: cBorder, width: 2, style: BorderStyle.solid),
        ),
        child: Column(
          children: [
            const Text('🎬', style: TextStyle(fontSize: 38)),
            const SizedBox(height: 10),
            Text('SELECTEAZĂ VIDEO',
              style: GoogleFonts.orbitron(
                fontSize: 13, fontWeight: FontWeight.w700,
                color: cText, letterSpacing: 1.2)),
            const SizedBox(height: 6),
            Text('MP4 · MKV · MOV · AVI · WMV · WebM · FLV\nCompresie reală FFmpeg · Identic cu Desktop EXE',
              textAlign: TextAlign.center,
              style: GoogleFonts.jetBrainsMono(
                fontSize: 10, color: cMuted, height: 1.7)),
            const SizedBox(height: 14),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 7),
              decoration: BoxDecoration(
                border: Border.all(color: cTeal),
                borderRadius: BorderRadius.circular(6),
              ),
              child: Text('↑ SELECTEAZĂ FIȘIERE',
                style: GoogleFonts.jetBrainsMono(
                  fontSize: 11, color: cTeal, letterSpacing: 1.2)),
            ),
          ],
        ),
      ),
    );
  }

  // ── Settings ──────────────────────────────────────────────────────────────
  Widget _buildSettings() {
    return Column(
      children: [
        // Row 1: Codec + Preset
        Row(
          children: [
            Expanded(child: _buildSelect('🎥 CODEC', _codec, [
              ('h265', 'H.265 / HEVC ★'),
              ('h264', 'H.264 / AVC'),
              ('vp9',  'VP9 / WebM'),
            ], (v) => setState(() => _codec = v!))),
            const SizedBox(width: 10),
            Expanded(child: _buildSelect('⚡ PRESET', _preset, [
              ('ultrafast', 'Ultrafast'),
              ('superfast', 'Superfast'),
              ('veryfast',  'Veryfast'),
              ('faster',    'Faster'),
              ('fast',      'Fast'),
              ('medium',    'Medium ★'),
              ('slow',      'Slow'),
              ('slower',    'Slower'),
            ], (v) => setState(() => _preset = v!))),
          ],
        ),
        const SizedBox(height: 10),
        // CRF Card
        _buildCrfCard(),
        const SizedBox(height: 10),
        // Row 2: Audio + Format
        Row(
          children: [
            Expanded(child: _buildSelect('🔊 AUDIO BITRATE', _abr, [
              ('64k',  '64k — Ușor'),
              ('96k',  '96k'),
              ('128k', '128k ★'),
              ('192k', '192k'),
              ('320k', '320k — Hi-Fi'),
            ], (v) => setState(() => _abr = v!))),
            const SizedBox(width: 10),
            Expanded(child: _buildSelect('📦 FORMAT', _format, [
              ('mp4',  'MP4 (universal)'),
              ('mkv',  'MKV'),
              ('webm', 'WebM'),
            ], (v) => setState(() => _format = v!))),
          ],
        ),
      ],
    );
  }

  Widget _buildSelect(String label, String value, List<(String, String)> items,
      ValueChanged<String?> onChanged) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: cSurf,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: cBorder),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: GoogleFonts.jetBrainsMono(
            fontSize: 9, color: cMuted, letterSpacing: 2.2)),
          const SizedBox(height: 8),
          DropdownButton<String>(
            value: value,
            isExpanded: true,
            dropdownColor: cCard,
            style: GoogleFonts.jetBrainsMono(fontSize: 12, color: cText),
            underline: const SizedBox(),
            items: items.map((e) => DropdownMenuItem(
              value: e.$1,
              child: Text(e.$2),
            )).toList(),
            onChanged: onChanged,
          ),
        ],
      ),
    );
  }

  Widget _buildCrfCard() {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: cSurf,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: cBorder),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('🎚 CALITATE (CRF)', style: GoogleFonts.jetBrainsMono(
                    fontSize: 9, color: cMuted, letterSpacing: 2.2)),
                  const SizedBox(height: 2),
                  Text('16=lossless → 40=max compresie',
                    style: GoogleFonts.jetBrainsMono(fontSize: 9, color: cMuted.withOpacity(0.7))),
                ],
              ),
              Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Text(_crf.round().toString(),
                    style: GoogleFonts.orbitron(
                      fontSize: 28, fontWeight: FontWeight.w900, color: cTeal)),
                  Text(_crfLabel,
                    style: GoogleFonts.jetBrainsMono(
                      fontSize: 9, color: _crfColor, letterSpacing: 0.8)),
                ],
              ),
            ],
          ),
          const SizedBox(height: 10),
          Slider(
            value: _crf,
            min: 16, max: 40, divisions: 24,
            label: _crf.round().toString(),
            onChanged: (v) => setState(() => _crf = v),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 4),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text('16 — Lossless', style: GoogleFonts.jetBrainsMono(fontSize: 9, color: cMuted)),
                Text('28 — Web', style: GoogleFonts.jetBrainsMono(fontSize: 9, color: cMuted)),
                Text('40 — Maxim', style: GoogleFonts.jetBrainsMono(fontSize: 9, color: cMuted)),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildToggle(String name, String desc, bool val, ValueChanged<bool> onChange) {
    return GestureDetector(
      onTap: () => onChange(!val),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 11),
        decoration: BoxDecoration(
          color: cSurf,
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: cBorder),
        ),
        child: Row(
          children: [
            Expanded(child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(name, style: GoogleFonts.jetBrainsMono(fontSize: 12, color: cText)),
                const SizedBox(height: 2),
                Text(desc, style: GoogleFonts.jetBrainsMono(fontSize: 9, color: cMuted)),
              ],
            )),
            const SizedBox(width: 12),
            AnimatedContainer(
              duration: const Duration(milliseconds: 250),
              width: 42, height: 22,
              decoration: BoxDecoration(
                color: val ? cTeal : cBorder,
                borderRadius: BorderRadius.circular(11),
              ),
              child: AnimatedAlign(
                duration: const Duration(milliseconds: 250),
                alignment: val ? Alignment.centerRight : Alignment.centerLeft,
                child: Container(
                  width: 16, height: 16,
                  margin: const EdgeInsets.all(3),
                  decoration: const BoxDecoration(
                    color: Colors.white, shape: BoxShape.circle),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  // ── Queue header ──────────────────────────────────────────────────────────
  Widget _buildQueueHeader() {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Text('COADĂ FIȘIERE', style: GoogleFonts.orbitron(
          fontSize: 10, fontWeight: FontWeight.w700, color: cMuted, letterSpacing: 2.0)),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
          decoration: BoxDecoration(
            color: cTeal.withOpacity(0.1),
            borderRadius: BorderRadius.circular(10),
          ),
          child: Text('${_queue.length} fișiere',
            style: GoogleFonts.jetBrainsMono(fontSize: 10, color: cTeal)),
        ),
      ],
    );
  }

  // ── Queue list ────────────────────────────────────────────────────────────
  Widget _buildQueue() {
    if (_queue.isEmpty) {
      return Container(
        width: double.infinity,
        padding: const EdgeInsets.all(30),
        decoration: BoxDecoration(
          color: cSurf,
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: cBorder, style: BorderStyle.solid),
        ),
        child: Text('FĂRĂ FIȘIERE — APASĂ SELECTEAZĂ',
          textAlign: TextAlign.center,
          style: GoogleFonts.jetBrainsMono(fontSize: 11, color: cMuted, letterSpacing: 1)),
      );
    }

    return Column(
      children: _queue.map(_buildJobCard).toList(),
    );
  }

  Widget _buildJobCard(VideoJob job) {
    final isActive = job.status == JobStatus.processing;
    final isDone   = job.status == JobStatus.done;
    final isErr    = job.status == JobStatus.error;

    Color borderColor = cBorder;
    if (isActive) borderColor = cTeal;
    if (isDone)   borderColor = cGreen.withOpacity(0.4);
    if (isErr)    borderColor = cDanger.withOpacity(0.3);

    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      decoration: BoxDecoration(
        color: cSurf,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: borderColor),
        boxShadow: isActive ? [BoxShadow(
          color: cTeal.withOpacity(0.08), blurRadius: 12)] : null,
      ),
      child: Column(
        children: [
          // File header row
          Padding(
            padding: const EdgeInsets.fromLTRB(13, 11, 8, 11),
            child: Row(
              children: [
                const Text('🎬', style: TextStyle(fontSize: 20)),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(job.name,
                        overflow: TextOverflow.ellipsis,
                        style: GoogleFonts.ibmPlexSans(
                          fontSize: 13, fontWeight: FontWeight.w500, color: cText)),
                      const SizedBox(height: 3),
                      Row(
                        children: [
                          Text(_fmtSize(job.size),
                            style: GoogleFonts.jetBrainsMono(fontSize: 10, color: cTeal)),
                          if (job.dims.isNotEmpty) ...[
                            const SizedBox(width: 10),
                            Text(job.dims,
                              style: GoogleFonts.jetBrainsMono(fontSize: 10, color: cMuted)),
                          ],
                          if (job.duration > 0) ...[
                            const SizedBox(width: 10),
                            Text(_fmtDur(job.duration),
                              style: GoogleFonts.jetBrainsMono(fontSize: 10, color: cMuted)),
                          ],
                        ],
                      ),
                    ],
                  ),
                ),
                if (!isActive)
                  IconButton(
                    icon: const Icon(Icons.close, size: 16, color: cMuted),
                    onPressed: () => _removeFile(job),
                    splashRadius: 16,
                  ),
              ],
            ),
          ),

          // Progress bar
          if (isActive || isDone) ...[
            ClipRRect(
              borderRadius: BorderRadius.zero,
              child: LinearProgressIndicator(
                value: job.progress / 100,
                backgroundColor: cBorder,
                valueColor: AlwaysStoppedAnimation<Color>(
                  isActive ? cTeal : cGreen),
                minHeight: 3,
              ),
            ),
            if (isActive && (job.fps.isNotEmpty || job.speed.isNotEmpty))
              Padding(
                padding: const EdgeInsets.fromLTRB(13, 4, 13, 6),
                child: Text(
                  [
                    if (job.fps.isNotEmpty) 'fps:${job.fps}',
                    if (job.speed.isNotEmpty) 'speed:${job.speed}',
                    '${job.progress.toStringAsFixed(0)}%',
                  ].join(' · '),
                  style: GoogleFonts.jetBrainsMono(fontSize: 10, color: cTeal),
                ),
              ),
          ],

          // Error message
          if (isErr && job.errorMsg != null)
            Padding(
              padding: const EdgeInsets.fromLTRB(13, 6, 13, 8),
              child: Text('✗ ${job.errorMsg}',
                style: GoogleFonts.jetBrainsMono(fontSize: 10, color: cDanger)),
            ),

          // Results panel
          if (isDone)
            Container(
              padding: const EdgeInsets.fromLTRB(13, 8, 13, 10),
              decoration: const BoxDecoration(
                color: Color(0x33000000),
                border: Border(top: BorderSide(color: cBorder)),
              ),
              child: Column(
                children: [
                  Row(
                    children: [
                      _statChip('ORIGINAL', _fmtSize(job.size), cText),
                      const SizedBox(width: 14),
                      _statChip('COMPRIMAT', _fmtSize(job.outputSize), cTeal),
                      const SizedBox(width: 14),
                      _statChip('ECONOMISIT',
                        job.savedPct,
                        job.savedNum >= 0 ? cGreen : cOrange),
                      const SizedBox(width: 14),
                      _statChip('RATIO', job.ratioStr, cText),
                      if (job.ssim != null) ...[
                        const SizedBox(width: 14),
                        _statChip('SSIM', job.ssim!, cText),
                        const SizedBox(width: 14),
                        _statChip('PIERDERE',
                          '${((1 - double.parse(job.ssim!)) * 100).toStringAsFixed(3)}%',
                          (1 - double.parse(job.ssim!)) * 100 > 2 ? cWarn : cGreen),
                      ],
                    ],
                  ),
                  const SizedBox(height: 10),
                  SizedBox(
                    width: double.infinity,
                    child: ElevatedButton.icon(
                      onPressed: () => _shareFile(job),
                      icon: const Icon(Icons.share, size: 16),
                      label: Text('DESCARCĂ / SHARE',
                        style: GoogleFonts.jetBrainsMono(
                          fontSize: 11, fontWeight: FontWeight.w700, letterSpacing: 1)),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: cTeal,
                        foregroundColor: Colors.black,
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(6)),
                        padding: const EdgeInsets.symmetric(vertical: 10),
                      ),
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }

  Widget _statChip(String label, String value, Color color) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: GoogleFonts.jetBrainsMono(
          fontSize: 7, color: cMuted, letterSpacing: 1.2)),
        const SizedBox(height: 2),
        Text(value, style: GoogleFonts.jetBrainsMono(
          fontSize: 12, fontWeight: FontWeight.w500, color: color)),
      ],
    );
  }

  // ── Action buttons ────────────────────────────────────────────────────────
  Widget _buildActions(bool hasPending) {
    return Row(
      children: [
        Expanded(
          child: ElevatedButton(
            onPressed: (!_working && hasPending) ? _compressAll : null,
            style: ElevatedButton.styleFrom(
              backgroundColor: cTeal,
              foregroundColor: Colors.black,
              disabledBackgroundColor: cTeal.withOpacity(0.3),
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
              padding: const EdgeInsets.symmetric(vertical: 14),
            ),
            child: Text('▶ COMPRESEAZĂ TOT',
              style: GoogleFonts.orbitron(
                fontSize: 12, fontWeight: FontWeight.w900, letterSpacing: 1.8)),
          ),
        ),
        const SizedBox(width: 10),
        OutlinedButton(
          onPressed: _working ? null : _clearQueue,
          style: OutlinedButton.styleFrom(
            foregroundColor: cOrange,
            side: const BorderSide(color: cBorder),
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
            padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 16),
          ),
          child: Text('✕ CURĂȚĂ',
            style: GoogleFonts.jetBrainsMono(fontSize: 12)),
        ),
      ],
    );
  }

  // ── Console ───────────────────────────────────────────────────────────────
  Widget _buildConsole() {
    return Container(
      decoration: BoxDecoration(
        color: const Color(0xFF05050d),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: cBorder),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(14, 8, 8, 8),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text('◈ SYSTEM LOG',
                  style: GoogleFonts.jetBrainsMono(
                    fontSize: 9, color: cMuted, letterSpacing: 2.0)),
                TextButton(
                  onPressed: () => setState(() => _log.clear()),
                  child: Text('[ CLEAR ]',
                    style: GoogleFonts.jetBrainsMono(fontSize: 9, color: cMuted)),
                ),
              ],
            ),
          ),
          const Divider(color: cBorder, height: 1),
          SizedBox(
            height: 160,
            child: ListView.builder(
              controller: _scrollCtrl,
              padding: const EdgeInsets.all(10),
              itemCount: _log.length,
              itemBuilder: (_, i) => Text(
                _log[i],
                style: GoogleFonts.jetBrainsMono(
                  fontSize: 10.5, color: cMuted, height: 1.8),
              ),
            ),
          ),
        ],
      ),
    );
  }

  // ── Helpers ───────────────────────────────────────────────────────────────
  String _fmtSize(int bytes) {
    if (bytes < 1024)       return '$bytes B';
    if (bytes < 1048576)    return '${(bytes/1024).toStringAsFixed(1)} KB';
    if (bytes < 1073741824) return '${(bytes/1048576).toStringAsFixed(1)} MB';
    return '${(bytes/1073741824).toStringAsFixed(2)} GB';
  }

  String _fmtDur(double s) {
    final m = (s / 60).floor();
    final sec = (s % 60).floor();
    return '$m:${sec.toString().padLeft(2, '0')}';
  }
}
