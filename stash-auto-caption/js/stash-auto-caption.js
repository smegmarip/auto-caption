(async () => {
  "use strict";

  /**
   * Reference to the global csLib object.
   * @constant {object}
   */
  const csLib = window.csLib;

  const { getPluginConfig, runPluginTask } = stashFunctions;

  /**
   * Plugin ID for the auto-caption RPC plugin.
   * @constant {string}
   */
  const PLUGIN_ID = "stash-auto-caption";

  /**
   * Plugin configuration cache.
   * @type {object|null}
   */
  let pluginConfig = null;

  /**
   * Language dictionary mapping language names to their respective codes.
   * @constant {object}
   */
  const LANG_DICT = {
    English: "en",
    Spanish: "es",
    French: "fr",
    German: "de",
    Italian: "it",
    Portuguese: "pt",
    Russian: "ru",
    Dutch: "nl",
    Japanese: "ja",
  };

  /**
   * Toast notification templates (non-React implementation).
   * @constant {object}
   */
  const toastTemplate = {
    top: `<div class="fade toast success show" role="alert" aria-live="assertive" aria-atomic="true">
      <div class="toast-header"><span class="mr-auto"></span><button type="button" class="close ml-2 mb-1" data-dismiss="toast"><span aria-hidden="true">×</span><span class="sr-only">Close</span></button></div>
      <div class="toast-body">`,
    bottom: `</div></div>`,
  };

  /**
   * Returns an array containing the scenario and scenario ID extracted from the current URL.
   * @returns {Array<string>} An array containing the scenario and scenario ID.
   */
  function getScenarioAndID() {
    var result = document.URL.match(/(movies|scenes)\/(\d+)/);
    var scenario = result[1];
    var scenario_id = result[2];
    return [scenario, scenario_id];
  }

  /**
   * Retrieves a scene with the given scene_id.
   *
   * @param {string} scene_id - The ID of the scene to retrieve.
   * @returns {Promise<Object>} - A promise that resolves with the scene object.
   */
  async function getScene(scene_id) {
    const reqData = {
      query: `{
          findScene(id: "${scene_id}") {
                id,
                captions {
                    language_code
                    caption_type
                    __typename
                }
                title,
                details,
                date,
                files {
                    duration
                    path
                }
                paths {
                    screenshot
                    caption
                }
                movies {
                    movie {
                        id,
                        name
                    }
                }
                studio {
                    id,
                    name
                }
                organized,
                tags {
                    id,
                    name
                },
                urls
            }
        }`,
    };
    var result = await csLib.callGQL(reqData);
    return result.findScene;
  }

  /**
   * Toggles the "Subtitled" tag for a given scene.
   *
   * @param {object} scene - The scene object to toggle the tag for.
   * @param {boolean} enable - Whether to add or remove the "Subtitled" tag.
   * @returns {Promise<void>} - A promise that resolves when the operation is complete.
   */
  async function toggleSubtitled(scene, enable) {
    const subtitledTag = await findTagByName("Subtitled");
    if (!subtitledTag) return;
    const sceneTags = scene.tags || [];
    const tagIds = sceneTags.map((tag) => tag.id);
    if (enable) {
      if (!tagIds.includes(subtitledTag.id)) {
        tagIds.push(subtitledTag.id);
        try {
          await updateSceneTags(scene.id, tagIds);
        } catch (e) {
          console.error("Error updating scene tags:", e);
        }
      }
    } else {
      if (tagIds.includes(subtitledTag.id)) {
        tagIds.splice(tagIds.indexOf(subtitledTag.id), 1);
        try {
          await updateSceneTags(scene.id, tagIds);
        } catch (e) {
          console.error("Error updating scene tags:", e);
        }
      }
    }
  }

  /**
   * Updates a scene with the given scene_id and tag_ids.
   * @param {string} scene_id - The ID of the scene to update.
   * @param {Array<string>} tag_ids - An array of tag IDs to associate with the scene.
   * @returns {Promise<Object>} - A promise that resolves with the updated scene object.
   */
  async function updateSceneTags(scene_id, tag_ids) {
    const reqData = {
      variables: { input: { id: scene_id, tag_ids: tag_ids } },
      query: `mutation sceneUpdate($input: SceneUpdateInput!){
        sceneUpdate(input: $input) {
          id
        }
      }`,
    };
    return csLib.callGQL(reqData);
  }

  /**
   * Retrieves the tag ID for a given tag name.
   *
   * @param {string} tagName - The name of the tag to retrieve the ID for.
   * @returns {Promise<object | null>} - A promise that resolves with the tag object.
   */
  async function findTagByName(tagName) {
    const reqData = {
      query: `{
          allTags{
            id
            name
            aliases
            children {
                id
                name
            }
          }
        }`,
    };
    var result = await csLib.callGQL(reqData);

    if ("allTags" in result) {
      return result.allTags.reduce((tag, obj) => {
        if (obj.name.toLowerCase() == tagName.toLowerCase()) {
          tag = obj;
        }
        return tag;
      }, null);
    }
    return null;
  }

  /**
   * Retrieves the status of a job with the given job ID.
   *
   * @param {string} jobId - The ID of the job to retrieve the status for.
   * @returns {Promise<object>} - A promise that resolves with the job status object.
   */
  async function getJobStatus(jobId) {
    const reqData = {
      variables: { id: jobId },
      query: `query ($id: ID!) {
            findJob(input: { id: $id }) {
                status
                progress
            }
        }`,
    };
    var result = await csLib.callGQL(reqData);
    return result;
  }

  /**
   * Waits for a job with the given job ID to finish, polling for progress updates.
   *
   * @param {string} jobId - The ID of the job to wait for.
   * @returns {Promise<boolean>} - A promise that resolves when the job is finished.
   */
  async function awaitJobFinished(jobId) {
    return new Promise((resolve, reject) => {
      const interval = setInterval(async () => {
        const result = await getJobStatus(jobId);
        const status = result.findJob?.status;
        const progress = result.findJob?.progress;

        // Update progress indicator if progress value is available
        if (typeof progress === "number" && progress >= 0) {
          updateCaptionProgress(progress);
        }

        // console.log(`Job status: ${status}, progress: ${progress}`)
        if (status === "FINISHED") {
          clearInterval(interval);
          updateCaptionProgress(1.0); // Set to 100% on completion
          resolve(true);
        } else if (status === "FAILED") {
          clearInterval(interval);
          reject(new Error("Job failed"));
        }
      }, 500); // Poll every 500ms for smoother progress updates
    });
  }

  /**
   * Displays a toast notification message.
   * @param {string} message - The message to display.
   */
  function addToast(message) {
    const $toast = $(toastTemplate.top + message + toastTemplate.bottom);
    const rmToast = () => $toast.remove();

    $toast.find("button.close").click(rmToast);
    $(".toast-container").append($toast);
    setTimeout(rmToast, 3000);
  }

  /**
   * Retrieves the caption URL for a given scene ID.
   *
   * @param {string} scene_id - The ID of the scene to retrieve the caption for.
   * @returns {Promise<string|null>} - A promise that resolves with the caption URL or null if not found.
   */
  async function getCaptionForScene(scene_id) {
    const scene = await getScene(scene_id);
    if (scene && scene.captions) {
      const caption = scene.captions.find(
        (c) => c.caption_type === "srt" && c.language_code === "en"
      );
      if (caption && scene.paths?.caption) {
        return `${scene.paths.caption}?lang=${caption.language_code}&type=${caption.caption_type}`;
      }
    }
    return null;
  }

  /**
   * Loads the caption into the video player.
   *
   * @param {string} captionUrl - The URL of the caption to load.
   * @returns {boolean} - True if the caption was successfully loaded, false otherwise.
   */
  function loadPlayerCaption(captionUrl) {
    const video = document.getElementById("VideoJsPlayer");
    if (video) {
      const player = video.player;
      if (player) {
        const lang = captionUrl.match(/lang=([^&]+)/)[1],
          label =
            Object.keys(LANG_DICT).find((key) => LANG_DICT[key] === lang) ||
            "English";
        player.addRemoteTextTrack(
          {
            kind: "captions",
            src: captionUrl,
            srclang: lang,
            label: label,
          },
          false
        );
        const tracks = player.remoteTextTracks();
        for (let i = 0; i < tracks.length; i++) {
          const track = tracks[i];
          if (track.kind === "captions" && track.language === "en") {
            track.mode = "showing";
          }
        }
        return true;
      }
    }
    return false;
  }

  /**
   * Adds a caption processing indicator to the video player control bar.
   *
   * @returns {HTMLElement|null} - The indicator element or null if player not found.
   */
  function addCaptionProcessingIndicator() {
    const player = document.getElementById("VideoJsPlayer");
    if (!player) return null;

    const controlBar = player.querySelector(".vjs-control-bar");
    if (!controlBar) return null;

    // Check if already exists
    if (document.getElementById("caption-processing-indicator")) {
      return document.getElementById("caption-processing-indicator");
    }

    // Add CSS for the indicator if not already added
    if (!document.getElementById("caption-indicator-styles")) {
      const style = document.createElement("style");
      style.id = "caption-indicator-styles";
      style.textContent = `
        #caption-processing-indicator {
          display: flex;
          align-items: center;
          justify-content: center;
          cursor: default;
          pointer-events: none;
          padding: 0;
          margin: 0;
          width: 3em;
          height: 100%;
        }
        #caption-processing-indicator .vjs-icon-wrapper {
          display: flex;
          align-items: center;
          justify-content: center;
        }
        #caption-processing-indicator svg {
          width: 1.8em;
          height: 1.8em;
          fill: #fff;
        }
        #caption-processing-indicator text {
          font-family: "Arial Narrow", "Liberation Sans Narrow", "Nimbus Sans Narrow", Arial, sans-serif;
          font-size: 20px;
          font-weight: normal;
          fill: #000;
          text-anchor: middle;
        }
      `;
      document.head.appendChild(style);
    }

    // Create indicator button
    const indicator = document.createElement("div");
    indicator.id = "caption-processing-indicator";
    indicator.className = "vjs-control vjs-button";
    indicator.title = "Generating captions...";
    indicator.style.display = "none";

    // Use captions SVG icon with progress text overlay
    indicator.innerHTML = `
      <div class="vjs-icon-wrapper">
        <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48">
          <rect x="6" y="8" width="36" height="32" rx="4" ry="4" />
          <text id="caption-progress-text" x="24" y="30" font-size="14" font-family="Arial Narrow, Liberation Sans Narrow, Nimbus Sans Narrow, Arial, sans-serif" font-weight="normal" fill="#000" text-anchor="middle">0%</text>
        </svg>
      </div>
    `;

    // Insert before caption button (or fullscreen if caption button doesn't exist)
    const captionBtn = controlBar.querySelector(".vjs-subs-caps-button");
    const fullscreenBtn = controlBar.querySelector(".vjs-fullscreen-control");
    if (captionBtn) {
      controlBar.insertBefore(indicator, captionBtn);
    } else if (fullscreenBtn) {
      controlBar.insertBefore(indicator, fullscreenBtn);
    } else {
      controlBar.appendChild(indicator);
    }

    return indicator;
  }

  /**
   * Updates the progress percentage displayed in the caption processing indicator.
   *
   * @param {number} progress - Progress value between 0 and 1.
   */
  function updateCaptionProgress(progress) {
    const progressText = document.getElementById("caption-progress-text");
    if (progressText) {
      const percentage = Math.round(progress * 100);
      progressText.textContent = `${percentage}`;
    }
  }

  /**
   * Shows the caption processing indicator in the video player.
   */
  function showCaptionProcessing() {
    const indicator = addCaptionProcessingIndicator();
    if (indicator) {
      indicator.style.display = "flex";
      updateCaptionProgress(0);
    }
  }

  /**
   * Hides the caption processing indicator in the video player.
   */
  function hideCaptionProcessing() {
    const indicator = document.getElementById("caption-processing-indicator");
    if (indicator) {
      indicator.style.display = "none";
    }
  }

  /**
   * Loads plugin configuration from Stash settings.
   * @returns {Promise<object>} - A promise that resolves with the plugin configuration.
   */
  async function loadPluginConfig() {
    if (pluginConfig) return pluginConfig;

    try {
      const config = await getPluginConfig(PLUGIN_ID);
      pluginConfig = {
        serviceUrl: config?.serviceUrl || "",
      };
      return pluginConfig;
    } catch (error) {
      console.error("Failed to load plugin config:", error);
      return { serviceUrl: "" };
    }
  }

  /**
   * Processes the remote caption for a given scene by triggering the Go RPC plugin.
   * This function is STATELESS - it only triggers the job and updates the UI.
   * All stateful operations (caption creation, tag management) are handled by the Go RPC plugin.
   *
   * @param {object} scene - The scene object to process the caption for.
   * @param {string} sceneLanguage - The language of the scene.
   * @returns {Promise<boolean>} - A promise that resolves when the caption processing is complete.
   */
  async function processRemoteCaption(scene, sceneLanguage) {
    if (!scene || !sceneLanguage) return false;
    const scene_id = scene.id;
    const videoPath = scene.files[0].path;
    const sceneTitle = scene.title || `Scene ${scene_id}`;

    try {
      console.log(
        `Starting caption generation for scene ${scene_id} (${sceneLanguage})`
      );

      // Load plugin settings
      const config = await loadPluginConfig();

      // Show progress indicators
      showCaptionProcessing();
      addToast(`Generating captions for "${sceneTitle}"...`);

      // Trigger the Go RPC plugin task
      // Note: The Go RPC plugin handles ALL stateful operations:
      // - Caption generation
      // - Tag management (adding "Subtitled" tag)
      // - Metadata scan triggering
      const result = await runPluginTask(
        PLUGIN_ID,
        "Generate Caption for Scene",
        [
          { key: "mode", value: { str: "generate" } },
          { key: "scene_id", value: { str: scene_id } },
          { key: "video_path", value: { str: videoPath } },
          { key: "language", value: { str: LANG_DICT[sceneLanguage] } },
          { key: "translate_to", value: { str: LANG_DICT["English"] } },
          { key: "service_url", value: { str: config.serviceUrl } },
        ]
      );

      if (!result || !result.runPluginTask) {
        console.error(
          "Failed to start caption generation task - no job ID returned"
        );
        hideCaptionProcessing();
        addToast("Failed to start caption generation");
        return false;
      }

      const jobId = result.runPluginTask;
      console.log(`Caption generation job started: ${jobId}`);

      try {
        await awaitJobFinished(jobId);
        console.log(`Caption generation job completed: ${jobId}`);
      } catch (jobError) {
        console.error(
          `Caption generation job failed: ${jobError.message || jobError}`
        );
        hideCaptionProcessing();
        addToast(
          `Caption generation failed: ${jobError.message || "Unknown error"}`
        );
        return false;
      }

      // Job completed successfully, update UI
      // Query scene again to get updated caption URL
      const captionUrl = await getCaptionForScene(scene_id);
      if (captionUrl) {
        console.log(`Caption loaded: ${captionUrl}`);
        const loaded = loadPlayerCaption(captionUrl);
        hideCaptionProcessing();
        if (loaded) {
          addToast("Captions generated successfully!");
        }
        return loaded;
      } else {
        console.warn("Caption generation completed but no caption file found");
        hideCaptionProcessing();
        addToast("Caption file not found after generation");
        return false;
      }
    } catch (error) {
      console.error("Error processing caption with RPC plugin:", error);
      hideCaptionProcessing();
      addToast(`Caption processing error: ${error.message || error}`);
      return false;
    }
  }

  /**
   * Detects the foreign language of a scene based on its tags.
   *
   * @param {object} scene - The scene object to detect the language for.
   * @returns {Promise<string|null>} - A promise that resolves with the detected language or null if not found.
   */
  async function detectForeignLanguage(scene) {
    const sceneTags = scene.tags || [];
    const flTag = await findTagByName("Foreign Language");
    if (flTag) {
      const registeredLangTags = flTag.children,
        supportedLangTags = registeredLangTags.filter((tag) =>
          Object.keys(LANG_DICT).includes(tag.name.replace(/ Language$/i, ""))
        ),
        sceneLanguage = sceneTags.reduce((lang, tag) => {
          if (!lang) {
            const sceneLangTag = supportedLangTags.find(
              (langTag) => langTag.id === tag.id
            );
            if (sceneLangTag) {
              lang = sceneLangTag.name.replace(/ Language$/i, "");
            }
          }
          return lang;
        }, null);
      return sceneLanguage;
    }
    return null;
  }

  /**
   * Detects if a scene already has captions and updates the "Subtitled" tag accordingly.
   *
   * @param {object} scene - The scene object to check for existing captions.
   * @returns {Promise<boolean>} - A promise that resolves with true if captions exist, false otherwise.
   */
  async function detectExistingCaption(scene) {
    if (scene.captions && scene.captions.length > 0 && scene.paths?.caption) {
      await toggleSubtitled(scene, true);
      return true;
    } else {
      await toggleSubtitled(scene, false);
      return false;
    }
  }

  csLib.PathElementListener("/scenes/", ".video-wrapper", async function (el) {
    const [_, scene_id] = getScenarioAndID();
    const scene = await getScene(scene_id);
    const videoPath = scene?.files[0]?.path;
    if (!scene || !videoPath) return;
    try {
      const hasCaption = await detectExistingCaption(scene);
      if (!hasCaption) {
        const sceneLanguage = await detectForeignLanguage(scene);
        if (sceneLanguage) {
          processRemoteCaption(scene, sceneLanguage).catch((error) => {
            console.error("Error processing remote caption:", error);
          });
        } else {
          // console.log("No foreign language tag detected for this scene.");
        }
      }
    } catch (error) {
      console.error("Error detecting foreign language:", error);
    }
  });
})();
