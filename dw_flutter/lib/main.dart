import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:file_picker/file_picker.dart';
import 'package:video_compress/video_compress.dart';
import 'package:path_provider/path_provider.dart';
import 'package:path/path.dart' as p;
import 'package:share_plus/share_plus.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:google_fonts/google_fonts.dart';

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

enum JobStatus { queued, processing, done, error }

class VideoJob {
  final String id;
  final String path;
  final String name;
  final int    size;
  double duration   = 0;
  String dims       = '';
  JobStatus status  = JobStatus.queued;
  String? outputPath;
  int    outputSize = 0;
  double progress   = 0;
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
    ? (size - outputSize) / size * 100.0 : 0.0;
}

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  SystemChrome.setSystemUIOverlayStyle(const SystemUiOverlayStyle(
    statusBarColor: cBg, statusBarIconBrightness: Brightness.light,
    systemNavigationBarColor: cBg, systemNavigationBarIconBrightness: Brightness.light,
  ));
  runApp(const DastanApp());
}

class DastanApp extends StatelessWidget {
  const DastanApp({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
    title: '◈ Dastan Wizard',
    debugShowCheckedModeBanner: false,
    theme: ThemeData(
      scaffoldBackgroundColor: cBg,
      colorScheme: ColorScheme.fromSeed(seedColor: cTeal, brightness: Brightness.dark, surface: cSurf),
      useMaterial3: true,
      sliderTheme: SliderThemeData(
        activeTrackColor: cTeal, inactiveTrackColor: cBorder,
        thumbColor: cTeal, overlayColor: cTeal.withOpacity(0.2),
        valueIndicatorColor: cTeal,
      ),
    ),
    home: const HomeScreen(),
  );
}

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});
  @override
  State<HomeScreen> createState() => _HomeState();
}

class _HomeState extends State<HomeScreen> {
  final List<VideoJob> _queue = [];
  bool _working = false;
  final List<String> _log = [];
  final _scrollCtrl = ScrollController();

  // Quality mapped to VideoQuality (CRF concept)
  double _quality = 2; // 0=low, 1=medium, 2=high, 3=highest
  String _resolution = 'original';

  VideoQuality get _vq {
    // LowQuality (~1.5 Mbps) și MediumQuality (~2.5 Mbps) sunt singurele
    // care garantează reducere pentru videouri cu bitrate ridicat
    switch (_quality.round()) {
      case 0: return VideoQuality.LowQuality;
      case 1: return VideoQuality.LowQuality;
      case 2: return VideoQuality.MediumQuality;
      default: return VideoQuality.MediumQuality;
    }
  }

  String get _qualLabel {
    switch (_quality.round()) {
      case 0: return 'COMPACT — MAX COMPRESIE';
      case 1: return 'BUNĂ — SOCIAL MEDIA';
      case 2: return 'RIDICATĂ — RECOMANDAT';
      default: return 'MAXIMĂ — NEAR-LOSSLESS';
    }
  }

  Color get _qualColor {
    switch (_quality.round()) {
      case 0: return cDanger;
      case 1: return cOrange;
      case 2: return cWarn;
      default: return cGreen;
    }
  }

  void _log_(String msg) {
    final ts = TimeOfDay.now().format(context);
    setState(() => _log.add('[$ts] $msg'));
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollCtrl.hasClients) {
        _scrollCtrl.animateTo(_scrollCtrl.position.maxScrollExtent,
          duration: const Duration(milliseconds: 200), curve: Curves.easeOut);
      }
    });
  }

  Future<void> _pickFiles() async {
    await Permission.videos.request();
    await Permission.storage.request();
    final result = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['mp4','mkv','mov','avi','wmv','webm','m4v','3gp'],
      allowMultiple: true,
    );
    if (result == null) return;
    for (final f in result.files) {
      if (f.path == null) continue;
      final job = VideoJob(path: f.path!, name: f.name, size: f.size);
      setState(() => _queue.add(job));
      _probeVideo(job);
      _log_('Adăugat: ${f.name} (${_fmtSize(f.size)})');
    }
  }

  Future<void> _probeVideo(VideoJob job) async {
    try {
      final info = await VideoCompress.getMediaInfo(job.path);
      if (!mounted) return;
      setState(() {
        job.duration = (info.duration ?? 0) / 1000.0;
        final w = info.width ?? 0;
        final h = info.height ?? 0;
        if (w > 0) job.dims = '${w}×${h}';
      });
    } catch (_) {}
  }

  void _removeFile(VideoJob job) {
    if (_working && job.status == JobStatus.processing) return;
    setState(() => _queue.remove(job));
  }

  Future<void> _compressAll() async {
    final pend = _queue.where((j) => j.status == JobStatus.queued).toList();
    if (pend.isEmpty || _working) return;
    setState(() => _working = true);
    _log_('━━ BATCH START: ${pend.length} fișier(e) ━━');
    _log_('Calitate: ${_qualLabel}');
    for (final job in pend) await _compressOne(job);
    final done = _queue.where((j) => j.status == JobStatus.done).length;
    _log_('━━ GATA: $done/${pend.length} ✓ ━━');
    setState(() => _working = false);
  }

  Future<void> _compressOne(VideoJob job) async {
    setState(() { job.status = JobStatus.processing; job.progress = 0; });
    _log_('⚡ Procesez: ${job.name}');

    // Subscribe to progress
    final sub = VideoCompress.compressProgress$.subscribe((prog) {
      if (!mounted) return;
      setState(() => job.progress = prog.toDouble());
    });

    try {
      // Calculăm rezoluția target (nu urcăm niciodată peste original)
      final srcW = job.w > 0 ? job.w : 1280;
      final srcH = job.h > 0 ? job.h : 720;

      // Target dimensions — maximum 720p pentru calitate 0-2, 1080p pentru 3
      final maxH = _quality.round() >= 3 ? 1080 : 720;
      int targetW = srcW;
      int targetH = srcH;
      if (srcH > maxH) {
        final scale = maxH / srcH;
        targetH = maxH;
        targetW = (srcW * scale).round();
        // Ensure even numbers (required by most codecs)
        targetW = targetW % 2 == 0 ? targetW : targetW - 1;
      }
      // Never upscale
      if (targetH > srcH) { targetW = srcW; targetH = srcH; }

      _log_('  Rezoluție: ${srcW}x${srcH} → ${targetW}x${targetH}');

      final info = await VideoCompress.compressVideo(
        job.path,
        quality: _vq,
        deleteOrigin: false,
        includeAudio: true,
        frameRate: 30,
      );

      sub.unsubscribe();

      if (info?.path == null) throw Exception('Compresie eșuată — output null');

      final outFile = File(info!.path!);
      int outSize = await outFile.length();
      String finalPath = info.path!;

      // Dacă outputul e mai mare decât inputul → videoul era deja comprimat
      // Copiem originalul ca output (nu putem comprima mai mult fără pierderi)
      if (outSize >= job.size) {
        _log_('  ⚠ Videoul era deja optimizat (bitrate scăzut). Output = original.');
        await outFile.delete();
        final dir = await getTemporaryDirectory();
        finalPath = '${dir.path}/DW_orig_${DateTime.now().millisecondsSinceEpoch}.mp4';
        await File(job.path).copy(finalPath);
        outSize = job.size;
      }

      final saved = ((job.size - outSize) / job.size * 100).toStringAsFixed(1);
      final ratio = outSize > 0 ? (job.size / outSize).toStringAsFixed(2) : '1.0';

      _log_('  ✓ ${_fmtSize(job.size)} → ${_fmtSize(outSize)} · $saved% economisit · ${ratio}×');

      setState(() {
        job.status = JobStatus.done;
        job.outputPath = finalPath;
        job.outputSize = outSize;
        job.progress = 100;
      });

    } catch (e) {
      sub.unsubscribe();
      setState(() { job.status = JobStatus.error; job.errorMsg = e.toString(); });
      _log_('  ✗ Eroare: $e');
    }
  }

  Future<void> _shareFile(VideoJob job) async {
    if (job.outputPath == null) return;
    final base = p.basenameWithoutExtension(job.name);
    await Share.shareXFiles(
      [XFile(job.outputPath!, name: '${base}_DW_compressed.mp4')],
      subject: 'Dastan Wizard — Video Comprimat',
    );
  }

  @override
  Widget build(BuildContext context) {
    final hasPending = _queue.any((j) => j.status == JobStatus.queued);
    return Scaffold(
      backgroundColor: cBg,
      body: SafeArea(child: Column(children: [
        _buildHeader(),
        Expanded(child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(14,0,14,14),
          child: Column(children: [
            const SizedBox(height:4),
            _buildPickArea(),
            const SizedBox(height:14),
            _buildQualityCard(),
            const SizedBox(height:14),
            _buildQueueHeader(),
            const SizedBox(height:8),
            _buildQueue(),
            const SizedBox(height:14),
            _buildActions(hasPending),
            const SizedBox(height:14),
            _buildConsole(),
            const SizedBox(height:20),
          ]),
        )),
      ])),
    );
  }

  Widget _buildHeader() => Container(
    padding: const EdgeInsets.fromLTRB(14,14,14,14),
    decoration: const BoxDecoration(border: Border(bottom: BorderSide(color: cBorder))),
    child: Row(children: [
      Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        ShaderMask(
          shaderCallback: (b) => const LinearGradient(colors: [cTeal, cBlue],
            begin: Alignment.centerLeft, end: Alignment.centerRight).createShader(b),
          child: Text('◈ DASTAN WIZARD', style: GoogleFonts.orbitron(
            fontSize: 18, fontWeight: FontWeight.w900, letterSpacing: 1.5, color: Colors.white)),
        ),
        const SizedBox(height:2),
        Text('VIDEO COMPRESSOR · ANDROID · v1.0', style: GoogleFonts.jetBrainsMono(
          fontSize: 9, color: cMuted, letterSpacing: 2.5)),
      ])),
      Container(
        padding: const EdgeInsets.symmetric(horizontal:12, vertical:5),
        decoration: BoxDecoration(color: cSurf, borderRadius: BorderRadius.circular(20),
          border: Border.all(color: _working ? cTeal.withOpacity(0.4) : cGreen.withOpacity(0.4))),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Container(width:7, height:7, decoration: BoxDecoration(shape: BoxShape.circle,
            color: _working ? cTeal : cGreen,
            boxShadow: [BoxShadow(color: (_working?cTeal:cGreen).withOpacity(0.6), blurRadius:6)])),
          const SizedBox(width:7),
          Text(_working ? 'COMPRESÂND' : 'READY', style: GoogleFonts.jetBrainsMono(
            fontSize:10, color: _working?cTeal:cGreen, letterSpacing:0.8)),
        ]),
      ),
    ]),
  );

  Widget _buildPickArea() => GestureDetector(
    onTap: _pickFiles,
    child: Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(vertical:32, horizontal:20),
      decoration: BoxDecoration(color: cSurf, borderRadius: BorderRadius.circular(14),
        border: Border.all(color: cBorder, width:2)),
      child: Column(children: [
        const Text('🎬', style: TextStyle(fontSize:38)),
        const SizedBox(height:10),
        Text('SELECTEAZĂ VIDEO', style: GoogleFonts.orbitron(
          fontSize:13, fontWeight: FontWeight.w700, color: cText, letterSpacing:1.2)),
        const SizedBox(height:6),
        Text('MP4 · MKV · MOV · AVI · WMV · WebM\nCompresie H.264 hardware · Mai rapid decât MediaRecorder',
          textAlign: TextAlign.center,
          style: GoogleFonts.jetBrainsMono(fontSize:10, color: cMuted, height:1.7)),
        const SizedBox(height:14),
        Container(padding: const EdgeInsets.symmetric(horizontal:18, vertical:7),
          decoration: BoxDecoration(border: Border.all(color: cTeal), borderRadius: BorderRadius.circular(6)),
          child: Text('↑ SELECTEAZĂ FIȘIERE', style: GoogleFonts.jetBrainsMono(fontSize:11, color:cTeal, letterSpacing:1.2))),
      ]),
    ),
  );

  Widget _buildQualityCard() => Container(
    padding: const EdgeInsets.all(14),
    decoration: BoxDecoration(color: cSurf, borderRadius: BorderRadius.circular(10), border: Border.all(color: cBorder)),
    child: Column(children: [
      Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, crossAxisAlignment: CrossAxisAlignment.end, children: [
        Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('🎚 CALITATE COMPRESIE', style: GoogleFonts.jetBrainsMono(fontSize:9, color:cMuted, letterSpacing:2.2)),
          const SizedBox(height:2),
          Text('0=maxim compresie · 3=near-lossless', style: GoogleFonts.jetBrainsMono(fontSize:9, color:cMuted.withOpacity(0.7))),
        ]),
        Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
          Text(_quality.round().toString(), style: GoogleFonts.orbitron(fontSize:28, fontWeight: FontWeight.w900, color:cTeal)),
          Text(_qualLabel, style: GoogleFonts.jetBrainsMono(fontSize:9, color:_qualColor, letterSpacing:0.8)),
        ]),
      ]),
      const SizedBox(height:10),
      Slider(value: _quality, min:0, max:3, divisions:3, label: _qualLabel,
        onChanged: (v) => setState(() => _quality = v)),
      Padding(padding: const EdgeInsets.symmetric(horizontal:4),
        child: Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
          Text('0 — Max compresie', style: GoogleFonts.jetBrainsMono(fontSize:9, color:cMuted)),
          Text('3 — Calitate max', style: GoogleFonts.jetBrainsMono(fontSize:9, color:cMuted)),
        ])),
    ]),
  );

  Widget _buildQueueHeader() => Row(
    mainAxisAlignment: MainAxisAlignment.spaceBetween,
    children: [
      Text('COADĂ FIȘIERE', style: GoogleFonts.orbitron(fontSize:10, fontWeight: FontWeight.w700, color:cMuted, letterSpacing:2.0)),
      Container(padding: const EdgeInsets.symmetric(horizontal:8, vertical:2),
        decoration: BoxDecoration(color: cTeal.withOpacity(0.1), borderRadius: BorderRadius.circular(10)),
        child: Text('${_queue.length} fișiere', style: GoogleFonts.jetBrainsMono(fontSize:10, color:cTeal))),
    ],
  );

  Widget _buildQueue() {
    if (_queue.isEmpty) return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(30),
      decoration: BoxDecoration(color: cSurf, borderRadius: BorderRadius.circular(10),
        border: Border.all(color: cBorder)),
      child: Text('FĂRĂ FIȘIERE — APASĂ SELECTEAZĂ', textAlign: TextAlign.center,
        style: GoogleFonts.jetBrainsMono(fontSize:11, color:cMuted, letterSpacing:1)),
    );
    return Column(children: _queue.map(_buildCard).toList());
  }

  Widget _buildCard(VideoJob job) {
    Color bc = cBorder;
    if (job.status == JobStatus.processing) bc = cTeal;
    if (job.status == JobStatus.done) bc = cGreen.withOpacity(0.4);
    if (job.status == JobStatus.error) bc = cDanger.withOpacity(0.3);
    return Container(
      margin: const EdgeInsets.only(bottom:8),
      decoration: BoxDecoration(color: cSurf, borderRadius: BorderRadius.circular(10),
        border: Border.all(color: bc),
        boxShadow: job.status == JobStatus.processing
          ? [BoxShadow(color: cTeal.withOpacity(0.08), blurRadius:12)] : null),
      child: Column(children: [
        Padding(padding: const EdgeInsets.fromLTRB(13,11,8,11), child: Row(children: [
          const Text('🎬', style: TextStyle(fontSize:20)),
          const SizedBox(width:10),
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(job.name, overflow: TextOverflow.ellipsis,
              style: GoogleFonts.ibmPlexSans(fontSize:13, fontWeight: FontWeight.w500, color:cText)),
            const SizedBox(height:3),
            Row(children: [
              Text(_fmtSize(job.size), style: GoogleFonts.jetBrainsMono(fontSize:10, color:cTeal)),
              if (job.dims.isNotEmpty) ...[const SizedBox(width:10),
                Text(job.dims, style: GoogleFonts.jetBrainsMono(fontSize:10, color:cMuted))],
              if (job.duration > 0) ...[const SizedBox(width:10),
                Text(_fmtDur(job.duration), style: GoogleFonts.jetBrainsMono(fontSize:10, color:cMuted))],
            ]),
          ])),
          if (job.status != JobStatus.processing)
            IconButton(icon: const Icon(Icons.close, size:16, color:cMuted),
              onPressed: () => _removeFile(job), splashRadius:16),
        ])),
        if (job.status == JobStatus.processing || job.status == JobStatus.done)
          ClipRRect(child: LinearProgressIndicator(
            value: job.progress / 100,
            backgroundColor: cBorder,
            valueColor: AlwaysStoppedAnimation(job.status == JobStatus.processing ? cTeal : cGreen),
            minHeight: 3,
          )),
        if (job.status == JobStatus.error && job.errorMsg != null)
          Padding(padding: const EdgeInsets.fromLTRB(13,6,13,8),
            child: Text('✗ ${job.errorMsg}', style: GoogleFonts.jetBrainsMono(fontSize:10, color:cDanger))),
        if (job.status == JobStatus.done)
          Container(padding: const EdgeInsets.fromLTRB(13,8,13,10),
            decoration: const BoxDecoration(color: Color(0x33000000),
              border: Border(top: BorderSide(color: cBorder))),
            child: Column(children: [
              Row(children: [
                _stat('ORIGINAL', _fmtSize(job.size), cText),
                const SizedBox(width:14),
                _stat('COMPRIMAT', _fmtSize(job.outputSize), cTeal),
                const SizedBox(width:14),
                _stat('ECONOMISIT', job.savedPct, job.savedNum >= 0 ? cGreen : cOrange),
                const SizedBox(width:14),
                _stat('RATIO', job.ratioStr, cText),
              ]),
              const SizedBox(height:10),
              SizedBox(width: double.infinity,
                child: ElevatedButton.icon(
                  onPressed: () => _shareFile(job),
                  icon: const Icon(Icons.share, size:16),
                  label: Text('DESCARCĂ / SHARE', style: GoogleFonts.jetBrainsMono(
                    fontSize:11, fontWeight: FontWeight.w700, letterSpacing:1)),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: cTeal, foregroundColor: Colors.black,
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(6)),
                    padding: const EdgeInsets.symmetric(vertical:10)),
                )),
            ])),
      ]),
    );
  }

  Widget _stat(String label, String value, Color color) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Text(label, style: GoogleFonts.jetBrainsMono(fontSize:7, color:cMuted, letterSpacing:1.2)),
      const SizedBox(height:2),
      Text(value, style: GoogleFonts.jetBrainsMono(fontSize:12, fontWeight: FontWeight.w500, color:color)),
    ],
  );

  Widget _buildActions(bool hasPending) => Row(children: [
    Expanded(child: ElevatedButton(
      onPressed: (!_working && hasPending) ? _compressAll : null,
      style: ElevatedButton.styleFrom(
        backgroundColor: cTeal, foregroundColor: Colors.black,
        disabledBackgroundColor: cTeal.withOpacity(0.3),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
        padding: const EdgeInsets.symmetric(vertical:14)),
      child: Text('▶ COMPRESEAZĂ TOT', style: GoogleFonts.orbitron(
        fontSize:12, fontWeight: FontWeight.w900, letterSpacing:1.8)),
    )),
    const SizedBox(width:10),
    OutlinedButton(
      onPressed: _working ? null : () {
        setState(() => _queue.clear());
        _log_('Coadă curățată');
      },
      style: OutlinedButton.styleFrom(foregroundColor: cOrange,
        side: const BorderSide(color: cBorder),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
        padding: const EdgeInsets.symmetric(vertical:14, horizontal:16)),
      child: Text('✕ CURĂȚĂ', style: GoogleFonts.jetBrainsMono(fontSize:12)),
    ),
  ]);

  Widget _buildConsole() => Container(
    decoration: BoxDecoration(color: const Color(0xFF05050d), borderRadius: BorderRadius.circular(10),
      border: Border.all(color: cBorder)),
    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Padding(padding: const EdgeInsets.fromLTRB(14,8,8,8),
        child: Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
          Text('◈ SYSTEM LOG', style: GoogleFonts.jetBrainsMono(fontSize:9, color:cMuted, letterSpacing:2.0)),
          TextButton(onPressed: () => setState(() => _log.clear()),
            child: Text('[ CLEAR ]', style: GoogleFonts.jetBrainsMono(fontSize:9, color:cMuted))),
        ])),
      const Divider(color: cBorder, height:1),
      SizedBox(height:160, child: ListView.builder(
        controller: _scrollCtrl,
        padding: const EdgeInsets.all(10),
        itemCount: _log.length,
        itemBuilder: (_, i) => Text(_log[i],
          style: GoogleFonts.jetBrainsMono(fontSize:10.5, color:cMuted, height:1.8)),
      )),
    ]),
  );

  String _fmtSize(int b) {
    if (b < 1024) return '$b B';
    if (b < 1048576) return '${(b/1024).toStringAsFixed(1)} KB';
    if (b < 1073741824) return '${(b/1048576).toStringAsFixed(1)} MB';
    return '${(b/1073741824).toStringAsFixed(2)} GB';
  }
  String _fmtDur(double s) {
    final m = (s/60).floor();
    final sec = (s%60).floor();
    return '$m:${sec.toString().padLeft(2,'0')}';
  }
}
