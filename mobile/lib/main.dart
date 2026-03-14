import 'dart:convert';
import 'dart:io';
import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:path/path.dart' show join;
import 'package:path_provider/path_provider.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final cameras = await availableCameras();
  final firstCamera = cameras.first;

  runApp(MaterialApp(
    theme: ThemeData(
      useMaterial3: true,
      colorScheme: ColorScheme.fromSeed(
        seedColor: Colors.blue,
        brightness: Brightness.dark,
      ),
    ),
    home: ScanScreen(camera: firstCamera),
    debugShowCheckedModeBanner: false,
  ));
}

class ScanScreen extends StatefulWidget {
  final CameraDescription camera;
  const ScanScreen({super.key, required this.camera});

  @override
  ScanScreenState createState() => ScanScreenState();
}

class ScanScreenState extends State<ScanScreen> {
  late CameraController _controller;
  late Future<void> _initializeControllerFuture;
  bool _isAnalyzing = false;
  final List<Map<String, dynamic>> _history = [];

  @override
  void initState() {
    super.initState();
    _controller = CameraController(widget.camera, ResolutionPreset.medium);
    _initializeControllerFuture = _controller.initialize();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _takePhotoAndAnalyze() async {
    setState(() { _isAnalyzing = true; });

    try {
      await _initializeControllerFuture;
      final image = await _controller.takePicture();

      // Adjust for your environment (10.0.2.2 for Android Emulator)
      String baseUrl = 'http://localhost:8001'; 

      var request = http.MultipartRequest('POST', Uri.parse('$baseUrl/analyze'));
      request.files.add(await http.MultipartFile.fromPath('image', image.path));

      var streamedResponse = await request.send().timeout(const Duration(seconds: 15));
      var response = await http.Response.fromStream(streamedResponse);

      if (response.statusCode == 200) {
        final result = json.decode(response.body);
        setState(() {
          _history.insert(0, result);
        });
        _showResultSheet(result);
      } else {
        _showError('Server error: ${response.statusCode}');
      }
    } catch (e) {
      _showError('Connection failed. Is the server running?');
    } finally {
      setState(() { _isAnalyzing = false; });
    }
  }

  void _showError(String msg) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg), backgroundColor: Colors.redAccent));
  }

  void _showResultSheet(Map<String, dynamic> result) {
    showModalBottomSheet(
      context: context,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (context) => Padding(
        padding: const EdgeInsets.all(24.0),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(result['product_name'] ?? 'Unknown Product', style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            Text('Brand: ${result['brand'] ?? 'N/A'}', style: Theme.of(context).textTheme.bodyLarge),
            Text('Price: ${result['price'] ?? 'N/A'}', style: Theme.of(context).textTheme.headlineSmall?.copyWith(color: Colors.greenAccent)),
            Text('Status: ${result['inventory_status'] ?? 'N/A'}'),
            const SizedBox(height: 20),
            Center(child: FilledButton(onPressed: () => Navigator.pop(context), child: const Text('Dismiss'))),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Store-Sense AI'), centerTitle: true),
      body: Column(
        children: [
          Container(
            height: 300,
            margin: const EdgeInsets.all(16),
            clipBehavior: Clip.antiAlias,
            decoration: BoxDecoration(borderRadius: BorderRadius.circular(24), border: Border.all(color: Colors.white10)),
            child: FutureBuilder<void>(
              future: _initializeControllerFuture,
              builder: (context, snapshot) {
                if (snapshot.connectionState == ConnectionState.done) {
                  return CameraPreview(_controller);
                } else {
                  return const Center(child: CircularProgressIndicator());
                }
              },
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16.0),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text('History', style: Theme.of(context).textTheme.titleLarge),
                if (_isAnalyzing) const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2)),
              ],
            ),
          ),
          Expanded(
            child: _history.isEmpty
                ? const Center(child: Text('No products scanned yet', style: TextStyle(color: Colors.grey)))
                : ListView.builder(
                    padding: const EdgeInsets.all(16),
                    itemCount: _history.length,
                    itemBuilder: (context, index) {
                      final item = _history[index];
                      return Card(
                        margin: const EdgeInsets.only(bottom: 12),
                        child: ListTile(
                          title: Text(item['product_name'] ?? 'Unknown'),
                          subtitle: Text('${item['brand']} • ${item['inventory_status']}'),
                          trailing: Text(item['price'] ?? '', style: const TextStyle(color: Colors.greenAccent, fontWeight: FontWeight.bold)),
                          onTap: () => _showResultSheet(item),
                        ),
                      );
                    },
                  ),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _isAnalyzing ? null : _takePhotoAndAnalyze,
        icon: const Icon(Icons.camera_alt),
        label: const Text('Scan Product'),
      ),
    );
  }
}
