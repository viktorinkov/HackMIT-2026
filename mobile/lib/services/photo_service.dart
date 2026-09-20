import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:image_picker/image_picker.dart';
import 'package:permission_handler/permission_handler.dart';

import '../theme/peel_theme.dart';
import '../widgets/peel_button.dart';

enum PhotoSource { camera, gallery }

enum PhotoOutcome { picked, cancelled, permissionDenied }

class PhotoPickResult {
  const PhotoPickResult(this.outcome, [this.file]);

  final PhotoOutcome outcome;
  final File? file;
}

/// Camera and gallery input with Android permission handling.
class PhotoService {
  PhotoService._();

  static final ImagePicker _picker = ImagePicker();

  static Future<PhotoPickResult> pick(PhotoSource source) async {
    if (source == PhotoSource.camera) {
      final status = await Permission.camera.request();
      if (!status.isGranted) {
        return const PhotoPickResult(PhotoOutcome.permissionDenied);
      }
    }
    try {
      final picked = await _picker.pickImage(
        source: source == PhotoSource.camera
            ? ImageSource.camera
            : ImageSource.gallery,
        maxWidth: 1600,
        imageQuality: 85,
      );
      if (picked == null) return const PhotoPickResult(PhotoOutcome.cancelled);
      return PhotoPickResult(PhotoOutcome.picked, File(picked.path));
    } on PlatformException {
      return const PhotoPickResult(PhotoOutcome.permissionDenied);
    }
  }
}

/// Bottom sheet that offers camera / gallery, then reports the outcome.
Future<File?> choosePhoto(BuildContext context, {required String title}) async {
  final source = await showModalBottomSheet<PhotoSource>(
    context: context,
    backgroundColor: PeelColors.surface,
    shape: const RoundedRectangleBorder(borderRadius: PeelRadii.r24),
    builder: (context) => SafeArea(
      child: Padding(
        padding: const EdgeInsets.all(PeelSpace.x24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(title, style: PeelText.heading),
            const SizedBox(height: PeelSpace.x16),
            PeelButton(
              label: 'Take a photo',
              onPressed: () => Navigator.pop(context, PhotoSource.camera),
            ),
            const SizedBox(height: PeelSpace.x12),
            PeelButton(
              label: 'Choose an existing photo',
              variant: PeelButtonVariant.secondary,
              onPressed: () => Navigator.pop(context, PhotoSource.gallery),
            ),
            const SizedBox(height: PeelSpace.x8),
            PeelButton(
              label: 'Cancel',
              variant: PeelButtonVariant.secondary,
              onPressed: () => Navigator.pop(context),
            ),
          ],
        ),
      ),
    ),
  );

  if (!context.mounted) return null;
  if (source == null) {
    _showNotice(context, 'No photo added. You can try again.');
    return null;
  }

  final result = await PhotoService.pick(source);
  if (!context.mounted) return null;

  switch (result.outcome) {
    case PhotoOutcome.picked:
      return result.file;
    case PhotoOutcome.cancelled:
      _showNotice(context, 'No photo added. You can try again.');
      return null;
    case PhotoOutcome.permissionDenied:
      await _showPermissionDialog(context);
      return null;
  }
}

void _showNotice(BuildContext context, String message) {
  ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(
      SnackBar(
        backgroundColor: PeelColors.ink,
        behavior: SnackBarBehavior.floating,
        content: Text(
          message,
          style: PeelText.body.copyWith(color: PeelColors.canvas),
        ),
      ),
    );
}

Future<void> _showPermissionDialog(BuildContext context) {
  return showDialog<void>(
    context: context,
    builder: (context) => AlertDialog(
      backgroundColor: PeelColors.surface,
      shape: const RoundedRectangleBorder(borderRadius: PeelRadii.r16),
      title: const Text('Camera access is off', style: PeelText.heading),
      content: const Text(
        'Peel needs the camera to take the photo. Turn it on in settings, or '
        'choose an existing photo instead.',
        style: PeelText.body,
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: Text('Not now', style: PeelText.label.copyWith(
            color: PeelColors.muted,
          )),
        ),
        TextButton(
          onPressed: () {
            Navigator.pop(context);
            openAppSettings();
          },
          child: Text(
            'Open settings',
            style: PeelText.label.copyWith(color: PeelColors.deep),
          ),
        ),
      ],
    ),
  );
}
