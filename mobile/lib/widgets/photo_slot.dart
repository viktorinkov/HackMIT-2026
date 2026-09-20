import 'dart:io';

import 'package:flutter/material.dart';

import '../theme/peel_theme.dart';
import 'animation_placeholder.dart';

/// The scan slot: animation placeholder until a photo exists, then a preview
/// of the photo the user took or chose.
class PhotoSlot extends StatelessWidget {
  const PhotoSlot({
    super.key,
    required this.photo,
    required this.description,
    this.empty,
    required this.onAdd,
    required this.onReplace,
    required this.onRemove,
  });

  final File? photo;
  final String description;

  /// Drawn in place of the placeholder before a photo is taken.
  final Widget? empty;
  final VoidCallback onAdd;
  final VoidCallback onReplace;
  final VoidCallback onRemove;

  @override
  Widget build(BuildContext context) {
    if (photo == null) {
      return GestureDetector(
        onTap: onAdd,
        child: empty ?? AnimationPlaceholder(description: description),
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        AspectRatio(
          aspectRatio: 364 / 416,
          child: ClipRRect(
            borderRadius: PeelRadii.r16,
            child: Container(
              color: PeelColors.camera,
              child: Image.file(photo!, fit: BoxFit.contain),
            ),
          ),
        ),
        const SizedBox(height: PeelSpace.x8),
        Row(
          children: [
            Expanded(
              child: TextButton(
                onPressed: onReplace,
                child: Text(
                  'Replace photo',
                  style: PeelText.label.copyWith(color: PeelColors.deep),
                ),
              ),
            ),
            Expanded(
              child: TextButton(
                onPressed: onRemove,
                child: Text(
                  'Remove photo',
                  style: PeelText.label.copyWith(color: PeelColors.muted),
                ),
              ),
            ),
          ],
        ),
      ],
    );
  }
}
