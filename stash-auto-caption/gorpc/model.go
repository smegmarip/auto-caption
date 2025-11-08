package main

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	graphql "github.com/hasura/go-graphql-client"
	"github.com/stashapp/stash/pkg/plugin/common/log"
)

// findForeignLanguageTag queries all tags and returns the "Foreign Language" tag with its children
func (a *autoCaptionAPI) findForeignLanguageTag() (*TagWithChildren, []TagFragment, error) {
	ctx := context.Background()

	var query struct {
		AllTags []struct {
			ID       graphql.ID    `graphql:"id"`
			Name     string        `graphql:"name"`
			Children []TagFragment `graphql:"children"`
		} `graphql:"allTags"`
	}

	err := a.graphqlClient.Query(ctx, &query, nil)
	if err != nil {
		return nil, nil, fmt.Errorf("failed to query tags: %w", err)
	}

	// Find "Foreign Language" tag
	for _, tag := range query.AllTags {
		if strings.EqualFold(tag.Name, "Foreign Language") {
			result := &TagWithChildren{
				ID:       tag.ID,
				Name:     tag.Name,
				Children: tag.Children,
			}
			return result, tag.Children, nil
		}
	}

	return nil, nil, nil
}

// findScenesWithLanguageTags queries scenes with any of the specified language tags
func (a *autoCaptionAPI) findScenesWithLanguageTags(languageTags []TagFragment) ([]SceneForBatch, error) {
	ctx := context.Background()

	// Build tag ID list
	tagIDStrings := []graphql.String{}
	for _, tag := range languageTags {
		tagIDStrings = append(tagIDStrings, graphql.String(tag.ID))
	}

	// Build query using typed structs
	var query struct {
		FindScenes FindScenesResult `graphql:"findScenes(filter: $f, scene_filter: $sf)"`
	}

	// Create filter input
	perPage := graphql.Int(5000)
	filterInput := &FindFilterType{
		PerPage: &perPage,
	}

	// Create scene filter with tags
	depth := graphql.Int(-1)
	tagsInput := &HierarchicalMultiCriterionInput{
		Value:    tagIDStrings,
		Modifier: "INCLUDES",
		Depth:    &depth,
	}
	sceneFilterInput := &SceneFilterType{
		Tags: tagsInput,
	}

	variables := map[string]interface{}{
		"f":  filterInput,
		"sf": sceneFilterInput,
	}

	err := a.graphqlClient.Query(ctx, &query, variables)
	if err != nil {
		return nil, fmt.Errorf("failed to query scenes: %w", err)
	}

	log.Debugf("FindScenes returned %d scenes (total count: %d)", len(query.FindScenes.Scenes), query.FindScenes.Count)

	return query.FindScenes.Scenes, nil
}

// scanCaptionMetadata triggers a metadata scan for the caption file
func (a *autoCaptionAPI) scanCaptionMetadata(captionPath string) error {
	ctx := context.Background()

	var mutation struct {
		MetadataScan graphql.String `graphql:"metadataScan(input: $input)"`
	}

	input := ScanMetadataInput{
		Paths: []string{captionPath},
	}

	variables := map[string]interface{}{
		"input": input,
	}

	err := a.graphqlClient.Mutate(ctx, &mutation, variables)
	if err != nil {
		return fmt.Errorf("metadata scan mutation failed: %w", err)
	}

	log.Infof("Triggered metadata scan for caption: %s", captionPath)
	return nil
}

// addSubtitledTag adds the "Subtitled" tag to a scene
func (a *autoCaptionAPI) addSubtitledTag(sceneID string) error {
	ctx := context.Background()

	// First, find the "Subtitled" tag ID
	var tagsQuery struct {
		AllTags []struct {
			ID   graphql.ID `graphql:"id"`
			Name string     `graphql:"name"`
		} `graphql:"allTags"`
	}

	err := a.graphqlClient.Query(ctx, &tagsQuery, nil)
	if err != nil {
		return fmt.Errorf("failed to query tags: %w", err)
	}

	var subtitledTagID graphql.ID
	for _, tag := range tagsQuery.AllTags {
		if strings.EqualFold(tag.Name, "Subtitled") {
			subtitledTagID = tag.ID
			break
		}
	}

	if subtitledTagID == "" {
		return fmt.Errorf("'Subtitled' tag not found - please create it in Stash")
	}

	// Get current scene tags
	var sceneQuery struct {
		FindScene SceneForBatch `graphql:"findScene(id: $f)"`
	}

	sceneVars := map[string]interface{}{
		"f": graphql.ID(sceneID),
	}

	err = a.graphqlClient.Query(ctx, &sceneQuery, sceneVars)
	if err != nil {
		return fmt.Errorf("failed to query scene: %w", err)
	}

	// Build new tag list (existing + Subtitled)
	tagIDs := []graphql.ID{}
	hasSubtitledTag := false
	for _, tag := range sceneQuery.FindScene.Tags {
		tagIDs = append(tagIDs, tag.ID)
		if tag.ID == subtitledTagID {
			hasSubtitledTag = true
		}
	}

	if hasSubtitledTag {
		log.Infof("Scene %s already has 'Subtitled' tag", sceneID)
		return nil
	}

	tagIDs = append(tagIDs, subtitledTagID)

	// Update scene with new tags
	type SceneUpdateInput struct {
		ID     graphql.ID   `json:"id"`
		TagIds []graphql.ID `json:"tag_ids"`
	}

	var updateMutation struct {
		SceneUpdate struct {
			ID graphql.ID
		} `graphql:"sceneUpdate(input: $input)"`
	}

	updateInput := SceneUpdateInput{
		ID:     graphql.ID(sceneID),
		TagIds: tagIDs,
	}

	updateVars := map[string]interface{}{
		"input": updateInput,
	}

	err = a.graphqlClient.Mutate(ctx, &updateMutation, updateVars)
	if err != nil {
		return fmt.Errorf("scene update mutation failed: %w", err)
	}

	log.Infof("Successfully added 'Subtitled' tag to scene %s", sceneID)
	return nil
}

// runPluginTaskForScene queues a caption generation task via GraphQL RunPluginTask
func (a *autoCaptionAPI) runPluginTaskForScene(ctx context.Context, scene *SceneForBatch, language string, serviceURL string) (string, error) {
	sceneID := string(scene.ID)
	videoPath := scene.Files[0].Path

	// Use args_map (newer approach) instead of deprecated args parameter
	var mutation struct {
		RunPluginTask graphql.ID `graphql:"runPluginTask(plugin_id: $pid, task_name: $tn, description: $desc, args_map: $am)"`
	}

	// Build args map
	argsMap := &Map{
		"mode":         "generate",
		"scene_id":     sceneID,
		"video_path":   videoPath,
		"language":     language,
		"translate_to": "en",
		"service_url":  serviceURL,
	}

	variables := map[string]interface{}{
		"pid":  graphql.ID("stash-auto-caption"),
		"tn":   graphql.String("Generate Caption for Scene"),
		"desc": graphql.String(fmt.Sprintf("Generating caption for %s", videoPath)),
		"am":   argsMap,
	}

	err := a.graphqlClient.Mutate(ctx, &mutation, variables)
	if err != nil {
		return "", fmt.Errorf("failed to run plugin task: %w", err)
	}

	jobID := string(mutation.RunPluginTask)
	log.Debugf("Queued job ID: %s", jobID)

	return jobID, nil
}

func (a *autoCaptionAPI) getPluginConfiguration() (PluginConfig, error) {
	pluginName := "stash-auto-caption"
	ctx := context.Background()

	query := `query Configuration {
		configuration {
		plugins
		}
	}`

	data, err := a.graphqlClient.ExecRaw(ctx, query, nil)
	if err != nil {
		return nil, fmt.Errorf("failed to query plugin configuration: %w", err)
	}

	// Unmarshal the response which has structure: {"configuration": {"plugins": {...}}}
	var response struct {
		Configuration PluginsConfiguration `json:"configuration"`
	}

	if err := json.Unmarshal(data, &response); err != nil {
		return nil, fmt.Errorf("failed to unmarshal plugin configuration: %w", err)
	}

	log.Debugf("Plugin configuration response: %+v", response)

	// Look up the plugin configuration by name
	if pluginConfig, ok := response.Configuration.Plugins[pluginName]; ok {
		return pluginConfig, nil
	}

	return nil, fmt.Errorf("plugin configuration not found for '%s'", pluginName)
}

// sceneHasCaption checks if a scene has caption metadata or an .srt file on disk
func (a *autoCaptionAPI) sceneHasCaption(scene *SceneForBatch) (bool, bool) {
	metadata := false
	file := false
	// Check 1: Caption metadata exists
	if len(scene.Captions) > 0 && scene.Paths != nil && scene.Paths.Caption != nil {
		log.Debugf("Scene %s has caption metadata", string(scene.ID))
		metadata = true
	}

	// Check 2: .srt file exists on disk
	if a.getCaptionPathForScene(scene) != nil {
		file = true
	}

	return metadata, file
}

func (a *autoCaptionAPI) getCaptionPathForScene(scene *SceneForBatch) *string {
	if len(scene.Files) > 0 {
		videoPath := scene.Files[0].Path
		srtPath := strings.TrimSuffix(videoPath, filepath.Ext(videoPath)) + ".en.srt"

		if _, err := os.Stat(srtPath); err == nil {
			log.Debugf("Scene %s has .srt file on disk: %s", string(scene.ID), srtPath)
			return &srtPath
		}
	}
	return nil
}

// detectSceneLanguage detects the language of a scene based on its tags
func (a *autoCaptionAPI) detectSceneLanguage(scene *SceneForBatch, supportedLangTags []TagFragment) string {
	// Find first matching language tag
	for _, sceneTag := range scene.Tags {
		for _, langTag := range supportedLangTags {
			if sceneTag.ID == langTag.ID {
				// Extract language name (e.g., "Spanish Language" -> "Spanish")
				langName := strings.TrimSuffix(sceneTag.Name, " Language")

				// Map to language code
				if code, ok := LANG_DICT[langName]; ok {
					return code
				}
			}
		}
	}

	// If multiple language tags found (shouldn't happen), return empty to trigger auto-detect
	return ""
}

// getIntSetting safely retrieves an integer argument, converting to int if necessary with parsing
func getIntSetting(setting map[string]interface{}, key string, defaultValue int) int {
	value, ok := setting[key]
	if !ok {
		// Key not found in the map
		return defaultValue
	}

	switch v := value.(type) {
	case int:
		return v
	case float64:
		// Common in JSON unmarshaling
		return int(v)
	case string:
		// Try parsing if it's a string
		if parsed, err := strconv.Atoi(v); err == nil {
			return parsed
		} else {
			// Log the parsing error if needed
			log.Tracef("Warning: failed to parse string value '%s' for key '%s' as int: %v\n", v, key, err)
		}
	}

	// Fallback if type is not recognized or string parsing failed
	return defaultValue
}
