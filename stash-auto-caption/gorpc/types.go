package main

import graphql "github.com/hasura/go-graphql-client"

// TagFragment represents a minimal tag with ID and name
type TagFragment struct {
	ID   graphql.ID `json:"id" graphql:"id"`
	Name string     `json:"name" graphql:"name"`
}

// VideoFile represents a video file
type VideoFile struct {
	Path     string  `json:"path" graphql:"path"`
	Duration float64 `json:"duration" graphql:"duration"`
}

// CaptionData represents caption metadata
type CaptionData struct {
	LanguageCode string `json:"language_code" graphql:"language_code"`
	CaptionType  string `json:"caption_type" graphql:"caption_type"`
}

// ScenePaths represents scene file paths
type ScenePaths struct {
	Screenshot string  `json:"screenshot" graphql:"screenshot"`
	Preview    *string `json:"preview,omitempty" graphql:"preview"`
	Stream     *string `json:"stream,omitempty" graphql:"stream"`
	Caption    *string `json:"caption,omitempty" graphql:"caption"`
}

// SceneForBatch represents a scene for batch processing
type SceneForBatch struct {
	ID       graphql.ID    `json:"id" graphql:"id"`
	Title    *string       `json:"title" graphql:"title"`
	Files    []VideoFile   `json:"files" graphql:"files"`
	Tags     []TagFragment `json:"tags" graphql:"tags"`
	Captions []CaptionData `json:"captions" graphql:"captions"`
	Paths    *ScenePaths   `json:"paths" graphql:"paths"`
}

// FindScenesResult represents the result of FindScenes query
type FindScenesResult struct {
	Count  graphql.Int
	Scenes []SceneForBatch
}

// TagWithChildren represents a tag with its children
type TagWithChildren struct {
	ID       graphql.ID    `json:"id" graphql:"id"`
	Name     string        `json:"name" graphql:"name"`
	Children []TagFragment `json:"children" graphql:"children"`
}

// ScanMetadataInput represents input for scanning metadata
type ScanMetadataInput struct {
	Paths []string `json:"paths" graphql:"paths"`
}

// SceneUpdateInput represents input for updating a scene's tags
type SceneUpdateInput struct {
	ID     graphql.ID   `json:"id" graphql:"id"`
	TagIds []graphql.ID `json:"tag_ids" graphql:"tag_ids"`
}

// SceneFragment represents a minimal scene with ID and tags
type SceneFragment struct {
	ID   graphql.ID     "json:\"id\" graphql:\"id\""
	Tags []*TagFragment "json:\"tags\" graphql:\"tags\""
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

// FindFilterType represents filter parameters for finding scenes
type FindFilterType struct {
	PerPage *graphql.Int    `graphql:"per_page" json:"per_page"`
	Sort    *graphql.String `graphql:"sort" json:"sort"`
}

// HierarchicalMultiCriterionInput represents tag filtering with hierarchy
type HierarchicalMultiCriterionInput struct {
	Value    []graphql.String `graphql:"value" json:"value"`
	Modifier graphql.String   `graphql:"modifier" json:"modifier"`
	Depth    *graphql.Int     `graphql:"depth" json:"depth"`
}

// SceneFilterType represents scene-specific filters
type SceneFilterType struct {
	Tags *HierarchicalMultiCriterionInput `graphql:"tags" json:"tags"`
}

// PluginArgInput represents an argument for plugin task (deprecated but working)
type PluginArgInput struct {
	Key   graphql.String    `graphql:"key" json:"key"`
	Value *PluginValueInput `graphql:"value" json:"value"`
}

// PluginValueInput represents the value of a plugin argument
type PluginValueInput struct {
	Str *graphql.String `graphql:"str" json:"str,omitempty"`
	I   *graphql.Int    `graphql:"i" json:"i,omitempty"`
}

// Map represents a GraphQL Map scalar
type Map map[string]interface{}

// PluginArgs represents an array of plugin arguments (note: type alias doesn't help with reflection)
// The library still can't properly generate [PluginArgInput!]! from this
type PluginArgs []*PluginArgInput

// PluginsConfiguration represents the plugins configuration result structure
type PluginsConfiguration struct {
	Plugins map[string]map[string]interface{} `json:"plugins"`
}

type PluginConfig = map[string]interface{}
