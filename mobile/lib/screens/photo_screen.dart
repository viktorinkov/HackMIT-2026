import 'dart:io';

import 'package:flutter/material.dart';

import '../services/photo_service.dart';
import '../theme/peel_theme.dart';
import '../widgets/peel_button.dart';

/// What the photo screen hands back. `null` from the route means the caller's
/// photo is unchanged; a result with a null [file] means it was removed.
class PhotoChoice {
  const PhotoChoice(this.file);

  final File? file;
}

/// Full-screen capture and preview, pushed as a fullscreen dialog so the app
/// bar's auto leading is an X rather than a back arrow. Taking, replacing and
/// removing a photo all happen here, so the scan screens never swap the shared
/// artboard out for a preview.
class PhotoScreen extends StatefulWidget {
  const PhotoScreen({super.key, required this.title, this.photo});

  final String title;
  final File? photo;

  static Future<PhotoChoice?> open(
    BuildContext context, {
    required String title,
    File? photo,
  }) {
    return Navigator.of(context).push<PhotoChoice>(
      MaterialPageRoute<PhotoChoice>(
        fullscreenDialog: true,
        builder: (_) => PhotoScreen(title: title, photo: photo),
      ),
    );
  }

  @override
  State<PhotoScreen> createState() => _PhotoScreenState();
}

class _PhotoScreenState extends State<PhotoScreen> {
  File? _photo;

  @override
  void initState() {
    super.initState();
    _photo = widget.photo;
  }

  Future<void> _pick() async {
    final file = await choosePhoto(context, title: widget.title);
    if (file == null || !mounted) return;
    setState(() => _photo = file);
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
                child: photo == null
                    ? const _Empty()
                    : ClipRRect(
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
              const SizedBox(height: PeelSpace.x16),
              if (photo == null)
                PeelButton(label: 'Add a photo', onPressed: _pick)
              else ...[
                PeelButton(
                  label: 'Use this photo',
                  onPressed: () =>
                      Navigator.of(context).pop(PhotoChoice(photo)),
                ),
                const SizedBox(height: PeelSpace.x8),
                PeelButton(
                  label: 'Replace photo',
                  variant: PeelButtonVariant.secondary,
                  onPressed: _pick,
                ),
                const SizedBox(height: PeelSpace.x8),
                PeelButton(
                  label: 'Remove photo',
                  variant: PeelButtonVariant.text,
                  onPressed: () =>
                      Navigator.of(context).pop(const PhotoChoice(null)),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _Empty extends StatelessWidget {
  const _Empty();

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: const BoxDecoration(
        color: PeelColors.soft,
        borderRadius: PeelRadii.r16,
      ),
      child: Center(
        child: Padding(
          padding: const EdgeInsets.all(PeelSpace.x24),
          child: Text(
            'Take a photo with the camera, or choose one you already have.',
            style: PeelText.body.copyWith(color: PeelColors.muted),
            textAlign: TextAlign.center,
          ),
        ),
      ),
    );
  }
}
