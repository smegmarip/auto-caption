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
	const hardcodedFallback = "http://auto-caption-web:8000"

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
	switch mode {
	case "generate":
		err = a.generateCaption(input)
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

	outputStr := "Caption generation completed successfully"
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

	return nil
}

// TaskStartRequest represents the request to start a caption task
type TaskStartRequest struct {
	VideoPath   string  `json:"video_path"`
	Language    string  `json:"language"`
	TranslateTo *string `json:"translate_to,omitempty"`
}

// TaskStartResponse represents the response from starting a task
type TaskStartResponse struct {
	TaskID string `json:"task_id"`
	Status string `json:"status"`
}

// TaskStatusResponse represents the task status response
type TaskStatusResponse struct {
	TaskID   string                 `json:"task_id"`
	Status   string                 `json:"status"`
	Progress float64                `json:"progress"`
	Stage    *string                `json:"stage"`
	Error    *string                `json:"error"`
	Result   map[string]interface{} `json:"result"`
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

// scanCaptionMetadata triggers a Stash metadata scan for the caption's directory
func (a *autoCaptionAPI) scanCaptionMetadata(captionPath string) error {
	// Extract parent directory
	var captionDir string
	for i := len(captionPath) - 1; i >= 0; i-- {
		if captionPath[i] == '/' || captionPath[i] == '\\' {
			captionDir = captionPath[:i]
			break
		}
	}

	if captionDir == "" {
		return fmt.Errorf("could not determine caption directory")
	}

	log.Infof("Triggering metadata scan for: %s", captionDir)

	// Execute GraphQL metadataScan mutation
	var mutation struct {
		MetadataScan graphql.String `graphql:"metadataScan(input: $input)"`
	}

	variables := map[string]interface{}{
		"input": map[string]interface{}{
			"paths": []string{captionDir},
		},
	}

	ctx := context.Background()
	err := a.graphqlClient.Mutate(ctx, &mutation, variables)
	if err != nil {
		return fmt.Errorf("failed to trigger metadata scan: %w", err)
	}

	jobID := string(mutation.MetadataScan)
	log.Infof("Metadata scan started with job ID: %s", jobID)

	return nil
}

// addSubtitledTag adds the "Subtitled" tag to a scene
func (a *autoCaptionAPI) addSubtitledTag(sceneID string) error {
	ctx := context.Background()

	// First, find the "Subtitled" tag
	var tagQuery struct {
		FindTag *struct {
			ID graphql.String
		} `graphql:"findTag(name: $tagName)"`
	}

	tagVariables := map[string]interface{}{
		"tagName": graphql.String("Subtitled"),
	}

	err := a.graphqlClient.Query(ctx, &tagQuery, tagVariables)
	if err != nil {
		return fmt.Errorf("failed to find 'Subtitled' tag: %w", err)
	}

	if tagQuery.FindTag == nil {
		return fmt.Errorf("'Subtitled' tag not found - please create it in Stash")
	}

	subtitledTagID := string(tagQuery.FindTag.ID)

	// Get current scene tags
	var sceneQuery struct {
		FindScene struct {
			Tags []struct {
				ID graphql.String
			}
		} `graphql:"findScene(id: $sceneId)"`
	}

	sceneVariables := map[string]interface{}{
		"sceneId": graphql.String(sceneID),
	}

	err = a.graphqlClient.Query(ctx, &sceneQuery, sceneVariables)
	if err != nil {
		return fmt.Errorf("failed to query scene: %w", err)
	}

	// Check if tag already exists
	tagIDs := []string{}
	hasSubtitledTag := false
	for _, tag := range sceneQuery.FindScene.Tags {
		tagID := string(tag.ID)
		tagIDs = append(tagIDs, tagID)
		if tagID == subtitledTagID {
			hasSubtitledTag = true
		}
	}

	if hasSubtitledTag {
		log.Infof("Scene %s already has 'Subtitled' tag", sceneID)
		return nil
	}

	// Add the Subtitled tag
	tagIDs = append(tagIDs, subtitledTagID)

	var updateMutation struct {
		SceneUpdate struct {
			ID graphql.String
		} `graphql:"sceneUpdate(input: $input)"`
	}

	updateVariables := map[string]interface{}{
		"input": map[string]interface{}{
			"id":      graphql.String(sceneID),
			"tag_ids": tagIDs,
		},
	}

	err = a.graphqlClient.Mutate(ctx, &updateMutation, updateVariables)
	if err != nil {
		return fmt.Errorf("failed to update scene tags: %w", err)
	}

	log.Infof("Successfully added 'Subtitled' tag to scene %s", sceneID)
	return nil
}
