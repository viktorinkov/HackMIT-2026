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

/// Full-screen preview of a photo that has already been taken or chosen,
/// pushed as a fullscreen dialog so the app bar's auto leading is an X rather
/// than a back arrow. Replacing and removing happen here, so the scan screens
/// never swap the shared artboard out for a preview.
class PhotoScreen extends StatefulWidget {
  const PhotoScreen({
    super.key,
    required this.title,
    required this.photo,
    required this.onReplaced,
  });

  final String title;
  final File photo;

  /// Called as soon as a replacement is picked, so the caller is up to date
  /// even if the screen is then closed with the X.
  final ValueChanged<File> onReplaced;

  static Future<PhotoChoice?> open(
    BuildContext context, {
    required String title,
    required File photo,
    required ValueChanged<File> onReplaced,
  }) {
    return Navigator.of(context).push<PhotoChoice>(
      MaterialPageRoute<PhotoChoice>(
        fullscreenDialog: true,
        builder: (_) => PhotoScreen(
          title: title,
          photo: photo,
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

  Future<void> _pick() async {
    final file = await choosePhoto(context, title: widget.title);
    if (file == null || !mounted) return;
    // Reported straight away, so closing with the X keeps the replacement.
    widget.onReplaced(file);
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
              const SizedBox(height: PeelSpace.x16),
              PeelButton(
                label: 'Use this photo',
                onPressed: () => Navigator.of(context).pop(PhotoChoice(photo)),
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
          ),
        ),
      ),
    );
  }
}
