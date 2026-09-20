import 'dart:io';

import 'package:flutter/material.dart';

import '../services/peel_api.dart';
import '../services/photo_service.dart';
import '../state/scan_session.dart';
import '../theme/peel_theme.dart';
import '../widgets/peel_button.dart';

/// What the photo screen hands back. `null` from the route means the caller's
/// photo is unchanged; a result with a null [file] means it was removed.
class PhotoChoice {
  const PhotoChoice(this.file);

  final File? file;
}

/// Full-screen preview of a photo that has already been taken or chosen,
/// pushed as a fullscreen dialog so the app bar's auto leading is an X rather
/// than a back arrow. Replacing and removing happen here, so the scan screens
/// never swap the shared artboard out for a preview.
class PhotoScreen extends StatefulWidget {
  const PhotoScreen({
    super.key,
    required this.title,
    required this.photo,
    required this.step,
    required this.onReplaced,
  });

  final String title;
  final File photo;
  final ScanStep step;

  /// Called as soon as a replacement is picked, so the caller is up to date
  /// even if the screen is then closed with the X.
  final ValueChanged<File> onReplaced;

  static Future<PhotoChoice?> open(
    BuildContext context, {
    required String title,
    required File photo,
    required ScanStep step,
    required ValueChanged<File> onReplaced,
  }) {
    return Navigator.of(context).push<PhotoChoice>(
      MaterialPageRoute<PhotoChoice>(
        fullscreenDialog: true,
        builder: (_) => PhotoScreen(
          title: title,
          photo: photo,
          step: step,
          onReplaced: onReplaced,
        ),
      ),
    );
  }

  @override
  State<PhotoScreen> createState() => _PhotoScreenState();
}

class _PhotoScreenState extends State<PhotoScreen> {
  late File _photo = widget.photo;
  bool _busy = false;
  String? _error;

  Future<void> _pick() async {
    final file = await choosePhoto(context, title: widget.title);
    if (file == null || !mounted) return;
    widget.onReplaced(file);
    scanSession.clearVision(widget.step);
    setState(() {
      _photo = file;
      _error = null;
    });
  }

  Future<void> _use() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await scanSession.identifyPhoto(widget.step, _photo);
      if (!mounted) return;
      Navigator.of(context).pop(PhotoChoice(_photo));
    } on PeelApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = error.message;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = error.toString();
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final photo = _photo;
    return Scaffold(
      backgroundColor: PeelColors.canvas,
      appBar: AppBar(
        backgroundColor: PeelColors.canvas,
        foregroundColor: PeelColors.ink,
        elevation: 0,
        title: Text(widget.title, style: PeelText.heading),
      ),
      body: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(
            PeelSpace.x24,
            PeelSpace.x8,
            PeelSpace.x24,
            PeelSpace.x16,
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Expanded(
                child: ClipRRect(
                  borderRadius: PeelRadii.r16,
                  child: ColoredBox(
                    color: PeelColors.camera,
                    child: Image.file(
                      photo,
                      fit: BoxFit.contain,
                      width: double.infinity,
                    ),
                  ),
                ),
              ),
              if (_error != null) ...[
                const SizedBox(height: PeelSpace.x12),
                Text(
                  _error!,
                  style: PeelText.body.copyWith(color: PeelColors.error),
                ),
              ],
              const SizedBox(height: PeelSpace.x16),
              PeelButton(
                label: _busy
                    ? 'Reading…'
                    : _error == null
                        ? 'Use this photo'
                        : 'Retry',
                onPressed: _busy ? null : _use,
              ),
              const SizedBox(height: PeelSpace.x8),
              PeelButton(
                label: 'Replace photo',
                variant: PeelButtonVariant.secondary,
                onPressed: _busy ? null : _pick,
              ),
              const SizedBox(height: PeelSpace.x8),
              PeelButton(
                label: 'Remove photo',
                variant: PeelButtonVariant.text,
                onPressed: _busy
                    ? null
                    : () => Navigator.of(context).pop(const PhotoChoice(null)),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
