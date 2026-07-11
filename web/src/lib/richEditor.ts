/**
 * Shared, full-featured TinyMCE configuration (self-hosted, GPL).
 *
 * One canonical rich-text config for every editor in the app (email composer,
 * email templates, user signatures, articles). Previously each editor imported a
 * different subset of plugins with a different toolbar, so e.g. the signature
 * editor had no font family / size / color controls. This module side-effect
 * imports the full self-hosted plugin set and exposes a single `richEditorInit()`
 * factory so every editor gets the same complete toolbar.
 *
 * What is intentionally NOT enabled: TinyMCE premium/cloud plugins
 * (powerpaste, tinymcespellchecker, a11ychecker, mentions, editimage, export,
 * advtable/advcode, formatpainter, checklist, pageembed, tableofcontents,
 * autocorrect, comments, revisionhistory, ai, …). Those require a paid API key
 * and are not part of the self-hosted GPL package, so they cannot be turned on
 * here. Also off by design: `save`/`autosave` (we own the Save button and don't
 * want localStorage draft-restore prompts).
 */
import "tinymce/tinymce";
import "tinymce/models/dom/model";
import "tinymce/themes/silver";
import "tinymce/icons/default";

// Every self-hosted plugin shipped in the npm package (v8) except save/autosave.
import "tinymce/plugins/accordion";
import "tinymce/plugins/advlist";
import "tinymce/plugins/anchor";
import "tinymce/plugins/autolink";
import "tinymce/plugins/charmap";
import "tinymce/plugins/code";
import "tinymce/plugins/codesample";
import "tinymce/plugins/directionality";
import "tinymce/plugins/emoticons";
import "tinymce/plugins/emoticons/js/emojis";
import "tinymce/plugins/fullscreen";
import "tinymce/plugins/help";
import "tinymce/plugins/help/js/i18n/keynav/en";
import "tinymce/plugins/image";
import "tinymce/plugins/importcss";
import "tinymce/plugins/insertdatetime";
import "tinymce/plugins/link";
import "tinymce/plugins/lists";
import "tinymce/plugins/media";
import "tinymce/plugins/nonbreaking";
import "tinymce/plugins/pagebreak";
import "tinymce/plugins/preview";
import "tinymce/plugins/quickbars";
import "tinymce/plugins/searchreplace";
import "tinymce/plugins/table";
import "tinymce/plugins/visualblocks";
import "tinymce/plugins/visualchars";
import "tinymce/plugins/wordcount";

// Skin (bundled) + editor-content CSS (inlined via content_style so the iframe
// gets styled without a network fetch, matching the self-hosted pattern).
import "tinymce/skins/ui/oxide/skin.css";
import contentUiCss from "tinymce/skins/ui/oxide/content.css?raw";
import contentCss from "tinymce/skins/content/default/content.css?raw";

export const RICH_PLUGINS = [
  "accordion", "advlist", "anchor", "autolink", "charmap", "code", "codesample",
  "directionality", "emoticons", "fullscreen", "help", "image", "importcss",
  "insertdatetime", "link", "lists", "media", "nonbreaking", "pagebreak",
  "preview", "quickbars", "searchreplace", "table", "visualblocks", "visualchars",
  "wordcount",
].join(" ");

export const RICH_MENUBAR = "file edit view insert format tools table help";

export const RICH_TOOLBAR = [
  "undo redo",
  "blocks fontfamily fontsize",
  "bold italic underline strikethrough",
  "forecolor backcolor removeformat",
  "alignleft aligncenter alignright alignjustify",
  "bullist numlist outdent indent",
  "link image media table",
  "blockquote codesample hr",
  "charmap emoticons insertdatetime",
  "ltr rtl",
  "searchreplace visualblocks code preview fullscreen help",
].join(" | ");

export const FONT_FAMILY_FORMATS = [
  "System UI=system-ui,'Segoe UI',Roboto,sans-serif",
  "Arial=Arial,Helvetica,sans-serif",
  "Arial Black=Arial Black,Gadget,sans-serif",
  "Georgia=Georgia,serif",
  "Times New Roman=Times New Roman,Times,serif",
  "Courier New=Courier New,Courier,monospace",
  "Tahoma=Tahoma,Geneva,sans-serif",
  "Trebuchet MS=Trebuchet MS,Helvetica,sans-serif",
  "Verdana=Verdana,Geneva,sans-serif",
].join(";");

export const FONT_SIZE_FORMATS = "8pt 9pt 10pt 11pt 12pt 14pt 16pt 18pt 24pt 30pt 36pt 48pt 60pt 72pt";

export const BRAND_COLOR_MAP = [
  "1b2a52", "Brand Navy",
  "ef3c1a", "Brand Red",
  "2b3c73", "Navy Text",
  "1a202c", "Dark Ink",
  "667085", "Subtle Grey",
  "1a7f4b", "Success Green",
  "b45309", "Amber",
  "000000", "Black",
  "ffffff", "White",
  "e5e7eb", "Light Border",
];

const BODY_STYLE =
  "body { font-family: system-ui, 'Segoe UI', Roboto, sans-serif; font-size: 15px; color: #1a202c; line-height: 1.6; }";

export interface RichEditorInit {
  [key: string]: unknown;
}

/**
 * Build a complete TinyMCE `init` object. Pass `overrides` for per-editor tweaks
 * (e.g. `{ height: 300 }` or `{ menubar: false }`).
 */
export function richEditorInit(overrides: RichEditorInit = {}): RichEditorInit {
  const extraContentStyle = typeof overrides.content_style === "string" ? overrides.content_style : "";
  const { content_style: _ignore, ...rest } = overrides;
  return {
    license_key: "gpl",
    skin: false,
    content_css: false,
    content_style: [contentUiCss, contentCss, BODY_STYLE, extraContentStyle].join("\n"),
    menubar: RICH_MENUBAR,
    plugins: RICH_PLUGINS,
    toolbar: RICH_TOOLBAR,
    toolbar_mode: "sliding",
    font_family_formats: FONT_FAMILY_FORMATS,
    font_size_formats: FONT_SIZE_FORMATS,
    color_map: BRAND_COLOR_MAP,
    branding: false,
    height: 360,
    ...rest,
  };
}
