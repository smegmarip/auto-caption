package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"strings"
	"time"

	graphql "github.com/hasura/go-graphql-client"
	"github.com/stashapp/stash/pkg/plugin/common"
	"github.com/stashapp/stash/pkg/plugin/common/log"
	"github.com/stashapp/stash/pkg/plugin/util"
)

func main() {
	err := common.ServePlugin(&autoCaptionAPI{})
	if err != nil {
		panic(err)
	}
}

type autoCaptionAPI struct {
	stopping         bool
	serverConnection common.StashServerConnection
	graphqlClient    *graphql.Client
}

// resolveServiceURL resolves the service URL with proper DNS lookup
// Handles IP addresses, hostnames, container names, and localhost
// Based on Stash's URL resolution approach
func resolveServiceURL(configuredURL string) string {
	const defaultContainerName = "auto-caption-web"
	const defaultPort = "8000"
	const defaultScheme = "http"
	var hardcodedFallback = fmt.Sprintf("%s://%s:%s", defaultScheme, defaultContainerName, defaultPort)

	// If no URL configured, use fallback
	if configuredURL == "" {
		configuredURL = hardcodedFallback
	}

	// Parse the URL
	parsedURL, err := url.Parse(configuredURL)
	if err != nil {
		log.Warnf("Failed to parse service URL '%s': %v, using fallback", configuredURL, err)
		return hardcodedFallback
	}

	hostname := parsedURL.Hostname()
	port := parsedURL.Port()
	scheme := parsedURL.Scheme

	// Default scheme if not specified
	if scheme == "" {
		scheme = defaultScheme
	}

	// Default port if not specified
	if port == "" {
		port = defaultPort
	}

	// Case 1: localhost - use as-is
	if hostname == "localhost" || hostname == "127.0.0.1" {
		resolvedURL := fmt.Sprintf("%s://%s:%s", scheme, hostname, port)
		log.Infof("Using localhost service URL: %s", resolvedURL)
		return resolvedURL
	}

	// Case 2: Already an IP address - use as-is
	if net.ParseIP(hostname) != nil {
		resolvedURL := fmt.Sprintf("%s://%s:%s", scheme, hostname, port)
		log.Infof("Using IP-based service URL: %s", resolvedURL)
		return resolvedURL
	}

	// Case 3: Hostname or container name - resolve via DNS
	log.Infof("Resolving hostname via DNS: %s", hostname)
	addrs, err := net.LookupIP(hostname)
	if err != nil {
		log.Warnf("DNS lookup failed for '%s': %v, using hostname as-is", hostname, err)
		// Return original URL even if DNS fails - it might still work
		resolvedURL := fmt.Sprintf("%s://%s:%s", scheme, hostname, port)
		return resolvedURL
	}

	if len(addrs) == 0 {
		log.Warnf("No IP addresses found for hostname '%s', using hostname as-is", hostname)
		resolvedURL := fmt.Sprintf("%s://%s:%s", scheme, hostname, port)
		return resolvedURL
	}

	// Use the first resolved IP address
	resolvedIP := addrs[0].String()
	resolvedURL := fmt.Sprintf("%s://%s:%s", scheme, resolvedIP, port)
	log.Infof("Resolved '%s' to %s", hostname, resolvedURL)
	return resolvedURL
}

func (a *autoCaptionAPI) Stop(input struct{}, output *bool) error {
	log.Info("Stopping auto-caption plugin...")
	a.stopping = true
	*output = true
	return nil
}

// Run handles the RPC task execution
func (a *autoCaptionAPI) Run(input common.PluginInput, output *common.PluginOutput) error {
	// Initialize GraphQL client from server connection
	a.serverConnection = input.ServerConnection
	a.graphqlClient = util.NewClient(input.ServerConnection)

	mode := input.Args.String("mode")

	var err error
	var outputStr string = "Unknown mode. Plugin did not run."
	switch mode {
	case "generate":
		err = a.generateCaption(input)
		outputStr = "Caption generation completed successfully"
	case "generateBatch":
		err = a.generateBatchCaptions(input)
		outputStr = "Caption generation started successfully"
	default:
		err = fmt.Errorf("unknown mode: %s", mode)
	}

	if err != nil {
		errStr := err.Error()
		*output = common.PluginOutput{
			Error: &errStr,
		}
		return nil
	}

	*output = common.PluginOutput{
		Output: &outputStr,
	}

	return nil
}

// generateCaption calls the auto-caption web service and polls for completion
func (a *autoCaptionAPI) generateCaption(input common.PluginInput) error {
	// Get parameters from input
	sceneID := input.Args.String("scene_id")
	videoPath := input.Args.String("video_path")
	language := input.Args.String("language")
	translateTo := input.Args.String("translate_to")
	serviceURL := input.Args.String("service_url")
	cooldownSeconds := getIntArg(input.Args, "cooldown_seconds", 0)

	if sceneID == "" {
		return fmt.Errorf("scene_id is required")
	}
	if videoPath == "" {
		return fmt.Errorf("video_path is required")
	}
	if language == "" {
		return fmt.Errorf("language is required")
	}

	// Resolve service URL with auto-detection
	serviceURL = resolveServiceURL(serviceURL)

	log.Infof("Generating caption for scene %s: %s (language: %s)", sceneID, videoPath, language)

	// Start caption generation task
	taskID, err := a.startCaptionTask(serviceURL, videoPath, language, translateTo)
	if err != nil {
		return fmt.Errorf("failed to start caption task: %w", err)
	}

	log.Infof("Caption task started: %s", taskID)

	// Poll for task completion
	err = a.pollTaskStatus(serviceURL, taskID)
	if err != nil {
		return err
	}

	// Caption generation succeeded, add "Subtitled" tag to scene
	log.Infof("Adding 'Subtitled' tag to scene %s", sceneID)
	if err := a.addSubtitledTag(sceneID); err != nil {
		log.Warnf("Failed to add 'Subtitled' tag: %v", err)
		// Don't fail the whole task if tag update fails
	}

	// Apply cooldown period if specified (for batch processing)
	if cooldownSeconds > 0 {
		log.Infof("Cooling down for %d seconds to prevent hardware stress...", cooldownSeconds)
		time.Sleep(time.Duration(cooldownSeconds) * time.Second)
	}

	return nil
}

func (a *autoCaptionAPI) startCaptionTask(serviceURL, videoPath, language, translateTo string) (string, error) {
	url := fmt.Sprintf("%s/auto-caption/start", serviceURL)

	req := TaskStartRequest{
		VideoPath: videoPath,
		Language:  language,
	}
	if translateTo != "" {
		req.TranslateTo = &translateTo
	}

	reqBody, err := json.Marshal(req)
	if err != nil {
		return "", err
	}

	resp, err := http.Post(url, "application/json", bytes.NewBuffer(reqBody))
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return "", fmt.Errorf("HTTP %d: %s", resp.StatusCode, string(body))
	}

	var taskResp TaskStartResponse
	if err := json.NewDecoder(resp.Body).Decode(&taskResp); err != nil {
		return "", err
	}

	return taskResp.TaskID, nil
}

func (a *autoCaptionAPI) pollTaskStatus(serviceURL, taskID string) error {
	url := fmt.Sprintf("%s/auto-caption/status/%s", serviceURL, taskID)
	ticker := time.NewTicker(2 * time.Second)
	defer ticker.Stop()

	for {
		if a.stopping {
			return fmt.Errorf("task interrupted")
		}

		select {
		case <-ticker.C:
			resp, err := http.Get(url)
			if err != nil {
				return fmt.Errorf("failed to get task status: %w", err)
			}

			var status TaskStatusResponse
			if err := json.NewDecoder(resp.Body).Decode(&status); err != nil {
				resp.Body.Close()
				return fmt.Errorf("failed to decode status: %w", err)
			}
			resp.Body.Close()

			// Update progress
			log.Progress(status.Progress)
			if status.Stage != nil {
				log.Infof("Stage: %s (%.0f%%)", *status.Stage, status.Progress*100)
			}

			// Check status
			switch status.Status {
			case "completed":
				log.Info("Caption generation completed successfully")
				var captionPath string
				if cp, ok := status.Result["caption_path"].(string); ok {
					captionPath = cp
					log.Infof("Caption saved to: %s", captionPath)
				}

				// Trigger metadata scan if caption was created
				if captionPath != "" {
					if err := a.scanCaptionMetadata(captionPath); err != nil {
						log.Warnf("Failed to trigger metadata scan: %v", err)
						// Don't fail the whole task if scan fails
					}
				}

				return nil

			case "failed":
				if status.Error != nil {
					return fmt.Errorf("caption generation failed: %s", *status.Error)
				}
				return fmt.Errorf("caption generation failed")

			case "queued", "running":
				// Continue polling
				continue

			default:
				return fmt.Errorf("unknown task status: %s", status.Status)
			}
		}
	}
}

// Language dictionary mapping language names to codes
var LANG_DICT = map[string]string{
	"English":    "en",
	"Spanish":    "es",
	"French":     "fr",
	"German":     "de",
	"Italian":    "it",
	"Portuguese": "pt",
	"Russian":    "ru",
	"Dutch":      "nl",
	"Japanese":   "ja",
	"Chinese":    "zh",
	"Korean":     "ko",
	"Arabic":     "ar",
}

// generateBatchCaptions finds all foreign language scenes without captions and queues them
func (a *autoCaptionAPI) generateBatchCaptions(input common.PluginInput) error {
	ctx := context.Background()
	serviceURL := input.Args.String("service_url")
	cooldownSeconds := getIntArg(input.Args, "cooldown_seconds", 10)
	maxBatchSize := getIntArg(input.Args, "max_batch_size", 20)

	log.Info("Starting batch caption generation for all foreign language scenes...")
	log.Infof("Configuration: max_batch_size=%d, cooldown_seconds=%d", maxBatchSize, cooldownSeconds)

	// Step 1: Find "Foreign Language" parent tag and its children
	foreignLangTag, foreignLangChildren, err := a.findForeignLanguageTag()
	if err != nil {
		return fmt.Errorf("failed to find Foreign Language tag: %w", err)
	}

	if foreignLangTag == nil {
		return fmt.Errorf("'Foreign Language' tag not found - please create it in Stash")
	}

	log.Debugf("Found 'Foreign Language' tag with %d children", len(foreignLangChildren))

	// Step 2: Build list of supported language tag IDs
	supportedLangTags := []TagFragment{}
	for _, childTag := range foreignLangChildren {
		// Check if this is a supported language (e.g., "Spanish Language")
		langName := strings.TrimSuffix(childTag.Name, " Language")
		if _, ok := LANG_DICT[langName]; ok {
			supportedLangTags = append(supportedLangTags, childTag)
		}
	}

	if len(supportedLangTags) == 0 {
		return fmt.Errorf("no supported language tags found (e.g., 'Spanish Language', 'Japanese Language')")
	}

	log.Tracef("Found %d supported language tags: %v", len(supportedLangTags), getSupportedLanguageNames(supportedLangTags))

	// Step 3: Query scenes with any of the foreign language tags
	scenes, err := a.findScenesWithLanguageTags(supportedLangTags)
	if err != nil {
		return fmt.Errorf("failed to find scenes: %w", err)
	}

	log.Infof("Found %d scenes with foreign language tags", len(scenes))

	// Step 4: Filter scenes to only those without captions
	scenesToProcess := []SceneForBatch{}
	for _, scene := range scenes {
		hasMetadata, hasFile := a.sceneHasCaption(&scene)
		if !hasFile {
			scenesToProcess = append(scenesToProcess, scene)
		} else if !hasMetadata {
			captionPath := a.getCaptionPathForScene(&scene)
			if captionPath != nil && *captionPath != "" {
				err := a.scanCaptionMetadata(*captionPath)
				if err != nil {
					log.Warnf("Failed to trigger metadata scan: %v", err)
				} else {
					a.addSubtitledTag(string(scene.ID))
				}
			}
		}
	}

	log.Infof("Filtered to %d scenes without captions", len(scenesToProcess))

	if len(scenesToProcess) == 0 {
		log.Info("No scenes to process - all foreign language scenes already have captions!")
		return nil
	}

	// Apply max batch size limit
	if len(scenesToProcess) > maxBatchSize {
		log.Warnf("Found %d scenes to process, but limiting to max_batch_size=%d to prevent hardware stress", len(scenesToProcess), maxBatchSize)
		scenesToProcess = scenesToProcess[:maxBatchSize]
	}

	// Step 5: Queue caption generation task for each scene
	log.Infof("Queueing %d scenes for caption generation...", len(scenesToProcess))

	queued := 0
	failed := 0

	for _, scene := range scenesToProcess {
		sceneTitle := "Unknown"
		if scene.Title != nil {
			sceneTitle = *scene.Title
		}

		// Detect language from tags
		language := a.detectSceneLanguage(&scene, supportedLangTags)
		if language == "" {
			log.Warnf("Scene %s (%s): Could not detect language, skipping", string(scene.ID), sceneTitle)
			failed++
			continue
		}

		// Get video path
		if len(scene.Files) == 0 {
			log.Warnf("Scene %s (%s): No video files found, skipping", string(scene.ID), sceneTitle)
			failed++
			continue
		}

		// Queue the task via RunPluginTask
		_, err := a.runPluginTaskForScene(ctx, &scene, language, serviceURL, cooldownSeconds)
		if err != nil {
			log.Errorf("Scene %s (%s): Failed to queue task: %v", string(scene.ID), sceneTitle, err)
			failed++
		} else {
			log.Infof("Scene %s (%s): Queued for caption generation (language: %s)", string(scene.ID), sceneTitle, language)
			queued++
		}
	}

	log.Infof("Batch processing complete: %d tasks queued, %d failed", queued, failed)

	return nil
}

// getSupportedLanguageNames returns a list of language names for logging
func getSupportedLanguageNames(tags []TagFragment) []string {
	names := []string{}
	for _, tag := range tags {
		names = append(names, tag.Name)
	}
	return names
}
