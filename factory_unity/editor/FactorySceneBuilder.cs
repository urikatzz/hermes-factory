// Factory scene builder + capture. Project-agnostic: it knows nothing about any game, only the factory-scene-layout/v1 file it is given.
// It runs inside the Unity Editor in batch mode (-executeMethod FactoryScene.BuildAndCapture), builds a real scene from the layout, renders it with the
// engine at the layout's resolution and writes engine-capture.json: facts only the engine process can state (version, graphics device, hashes, renderers).
using System;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.SceneManagement;

public static class FactoryScene
{
    [Serializable] public class Camera2 { public bool orthographic = true; public float size = 9f; public float[] position = { 0, 0, -10 }; public float[] background = { 0, 0, 0, 1 }; public int width = 1280; public int height = 720; }
    [Serializable] public class Obj
    {
        public string id; public string name; public string asset; public float[] position = { 0, 0, 0 }; public float[] size_units; public float[] scale; public int sorting_order;
        public float pixels_per_unit = 0f; public bool flip_x; public string[] covers; public float[] pivot;
    }
    [Serializable] public class Layout { public string schema; public string scene; public string lighting = "unlit"; public Camera2 camera = new Camera2(); public Obj[] objects = new Obj[0]; }

    static string Arg(string name)
    {
        var args = Environment.GetCommandLineArgs();
        for (int i = 0; i < args.Length - 1; i++) if (args[i] == name) return args[i + 1];
        return null;
    }

    static string Sha256(byte[] data) { using (var h = SHA256.Create()) { var sb = new StringBuilder(); foreach (var b in h.ComputeHash(data)) sb.Append(b.ToString("x2")); return sb.ToString(); } }
    static string Esc(string s) { return (s ?? "").Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\n", " ").Replace("\r", " "); }
    static float F(float[] v, int i, float d) { return v != null && v.Length > i ? v[i] : d; }

    public static void BuildAndCapture()
    {
        int code = 0;
        try { Run(); }
        catch (Exception e) { Debug.LogError("FactoryScene failed: " + e); code = 3; }
        EditorApplication.Exit(code);
    }

    static void Run()
    {
        var layoutPath = Arg("-factoryLayout"); var outDir = Arg("-factoryOut");
        if (string.IsNullOrEmpty(layoutPath) || string.IsNullOrEmpty(outDir)) throw new Exception("-factoryLayout and -factoryOut are required");
        Directory.CreateDirectory(outDir);
        var layoutBytes = File.ReadAllBytes(layoutPath);
        var layout = JsonUtility.FromJson<Layout>(Encoding.UTF8.GetString(layoutBytes));
        if (layout == null || layout.schema != "factory-scene-layout/v1") throw new Exception("layout is not factory-scene-layout/v1");
        if (string.IsNullOrEmpty(layout.scene) || !layout.scene.StartsWith("Assets/") || !layout.scene.EndsWith(".unity")) throw new Exception("layout.scene must be an Assets/*.unity path");

        // 1. Import every asset as a sprite (the engine decides what a sprite is: nothing is composited outside the engine).
        foreach (var o in layout.objects)
        {
            if (string.IsNullOrEmpty(o.asset) || !File.Exists(o.asset)) throw new Exception("asset missing in the project: " + o.asset);
            AssetDatabase.ImportAsset(o.asset, ImportAssetOptions.ForceSynchronousImport);
            var importer = (TextureImporter)AssetImporter.GetAtPath(o.asset);
            if (importer == null) throw new Exception("not a texture: " + o.asset);
            int w = 0, h = 0; importer.GetSourceTextureWidthAndHeight(out w, out h);
            float ppu = o.pixels_per_unit > 0 ? o.pixels_per_unit : (o.size_units != null && o.size_units.Length >= 1 && o.size_units[0] > 0 ? w / o.size_units[0] : 100f);
            importer.textureType = TextureImporterType.Sprite; importer.spriteImportMode = SpriteImportMode.Single; importer.spritePixelsPerUnit = ppu;
            if (o.pivot != null && o.pivot.Length >= 2) { importer.spriteAlignment = (int)SpriteAlignment.Custom; importer.spritePivot = new Vector2(o.pivot[0], o.pivot[1]); }
            importer.mipmapEnabled = false; importer.alphaIsTransparency = true; importer.filterMode = FilterMode.Bilinear; importer.textureCompression = TextureImporterCompression.Uncompressed;
            importer.SaveAndReimport();
        }

        // 2. Build a real scene.
        var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
        var camGo = new GameObject("Main Camera"); camGo.tag = "MainCamera";
        var cam = camGo.AddComponent<Camera>();
        cam.orthographic = layout.camera.orthographic; cam.orthographicSize = layout.camera.size;
        cam.transform.position = new Vector3(F(layout.camera.position, 0, 0), F(layout.camera.position, 1, 0), F(layout.camera.position, 2, -10));
        cam.clearFlags = CameraClearFlags.SolidColor;
        cam.backgroundColor = new Color(F(layout.camera.background, 0, 0), F(layout.camera.background, 1, 0), F(layout.camera.background, 2, 0), F(layout.camera.background, 3, 1));
        cam.nearClipPlane = 0.1f; cam.farClipPlane = 100f;
        var placed = new List<string>();
        // Assets are shown as authored: unlit by default, because a freshly assembled scene has no 2D lights and the lit sprite shader would render it black.
        Material unlit = null;
        if (layout.lighting != "project")
        {
            foreach (var guid in AssetDatabase.FindAssets("Sprite-Unlit-Default t:Material")) { unlit = AssetDatabase.LoadAssetAtPath<Material>(AssetDatabase.GUIDToAssetPath(guid)); if (unlit != null) break; }
            if (unlit == null) unlit = AssetDatabase.GetBuiltinExtraResource<Material>("Sprites-Default.mat");
        }
        foreach (var o in layout.objects)
        {
            var go = new GameObject(string.IsNullOrEmpty(o.name) ? o.id : o.name);
            var sprite = AssetDatabase.LoadAssetAtPath<Sprite>(o.asset);
            if (sprite == null) throw new Exception("not importable as a sprite: " + o.asset);
            var sr = go.AddComponent<SpriteRenderer>(); sr.sprite = sprite; sr.sortingOrder = o.sorting_order; sr.flipX = o.flip_x; if (unlit != null) sr.sharedMaterial = unlit;
            go.transform.position = new Vector3(F(o.position, 0, 0), F(o.position, 1, 0), F(o.position, 2, 0));
            if (o.scale != null && o.scale.Length >= 2) go.transform.localScale = new Vector3(o.scale[0], o.scale[1], 1f);
            placed.Add(o.id);
        }
        Directory.CreateDirectory(Path.GetDirectoryName(layout.scene));   // a project may have no scene folder yet
        if (!EditorSceneManager.SaveScene(scene, layout.scene)) throw new Exception("could not save the scene");
        AssetDatabase.Refresh();

        // 3. Render with the engine at the layout's resolution.
        int W = layout.camera.width, H = layout.camera.height;
        var rt = new RenderTexture(W, H, 24, RenderTextureFormat.ARGB32, RenderTextureReadWrite.sRGB) { antiAliasing = 1 };
        cam.targetTexture = rt;
        // Render twice and keep the second: in a freshly built scene the first pass can still use the previous sprite's texture binding (observed: every sprite drawn with the first
        // sprite's texture), so the first pass only primes the renderers.
        for (int pass = 0; pass < 2; pass++)
        {
            foreach (var sr in UnityEngine.Object.FindObjectsByType<SpriteRenderer>()) { var s = sr.sprite; sr.sprite = null; sr.sprite = s; sr.ResetBounds(); }
            var request = new RenderPipeline.StandardRequest { destination = rt };
            if (RenderPipeline.SupportsRenderRequest(cam, request)) RenderPipeline.SubmitRenderRequest(cam, request); else cam.Render();
        }
        var prev = RenderTexture.active; RenderTexture.active = rt;
        var tex = new Texture2D(W, H, TextureFormat.RGBA32, false, false); tex.ReadPixels(new Rect(0, 0, W, H), 0, 0); tex.Apply();
        RenderTexture.active = prev; cam.targetTexture = null;
        var png = tex.EncodeToPNG();
        var pngPath = Path.Combine(outDir, "scene.png"); File.WriteAllBytes(pngPath, png);
        File.Copy(layout.scene, Path.Combine(outDir, Path.GetFileName(layout.scene)), true);

        // 4. Engine attestation: facts the engine process itself states about this render.
        var sb = new StringBuilder("{\n");
        sb.Append("  \"schema\": \"factory-engine-capture/v1\",\n");
        sb.Append("  \"engine\": \"Unity\", \"engine_version\": \"" + Esc(Application.unityVersion) + "\",\n");
        sb.Append("  \"graphics_device\": \"" + Esc(SystemInfo.graphicsDeviceName) + "\", \"graphics_api\": \"" + SystemInfo.graphicsDeviceType + "\",\n");
        sb.Append("  \"platform\": \"" + Application.platform + "\", \"render_pipeline\": \"" + Esc(GraphicsSettings.currentRenderPipeline != null ? GraphicsSettings.currentRenderPipeline.name : "built-in") + "\",\n");
        sb.Append("  \"scene\": \"" + Esc(layout.scene) + "\", \"scene_sha256\": \"" + Sha256(File.ReadAllBytes(layout.scene)) + "\", \"layout_sha256\": \"" + Sha256(layoutBytes) + "\",\n");
        sb.Append("  \"screenshot\": \"scene.png\", \"screenshot_sha256\": \"" + Sha256(png) + "\", \"width\": " + W + ", \"height\": " + H + ",\n");
        sb.Append("  \"lighting\": \"" + Esc(layout.lighting) + "\",\n");
        sb.Append("  \"camera\": {\"orthographic\": " + (cam.orthographic ? "true" : "false") + ", \"size\": " + cam.orthographicSize.ToString(System.Globalization.CultureInfo.InvariantCulture) + "},\n");
        sb.Append("  \"captured_at\": " + DateTimeOffset.UtcNow.ToUnixTimeSeconds() + ",\n  \"renderers\": [");
        bool first = true;
        foreach (var sr in UnityEngine.Object.FindObjectsByType<SpriteRenderer>())
        {
            var path = AssetDatabase.GetAssetPath(sr.sprite);
            if (!first) sb.Append(","); first = false;
            var b = sr.bounds;
            sb.Append("\n    {\"object\": \"" + Esc(sr.gameObject.name) + "\", \"asset\": \"" + Esc(path) + "\", \"guid\": \"" + AssetDatabase.AssetPathToGUID(path) + "\", \"asset_sha256\": \"" + Sha256(File.ReadAllBytes(path)) + "\", ");
            sb.Append("\"material\": \"" + Esc(sr.sharedMaterial != null ? sr.sharedMaterial.name : "none") + "\", \"shader\": \"" + Esc(sr.sharedMaterial != null ? sr.sharedMaterial.shader.name : "none") + "\", \"sorting_order\": " + sr.sortingOrder + ", \"vertices\": " + sr.sprite.vertices.Length + ", \"texture\": \"" + sr.sprite.texture.width + "x" + sr.sprite.texture.height + "\", \"ppu\": " + sr.sprite.pixelsPerUnit.ToString(System.Globalization.CultureInfo.InvariantCulture) + ", ");
            sb.Append("\"bounds_min\": [" + b.min.x.ToString(System.Globalization.CultureInfo.InvariantCulture) + "," + b.min.y.ToString(System.Globalization.CultureInfo.InvariantCulture) + "], \"bounds_max\": [" + b.max.x.ToString(System.Globalization.CultureInfo.InvariantCulture) + "," + b.max.y.ToString(System.Globalization.CultureInfo.InvariantCulture) + "]}");
        }
        sb.Append("\n  ],\n  \"objects_placed\": " + placed.Count + "\n}\n");
        File.WriteAllText(Path.Combine(outDir, "engine-capture.json"), sb.ToString());
        Debug.Log("FactoryScene: captured " + W + "x" + H + " on " + SystemInfo.graphicsDeviceName + " with " + placed.Count + " objects");
    }
}
