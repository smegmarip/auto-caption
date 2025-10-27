(async () => {
  "use strict";

  /**
   * Reference to the global csLib object.
   * @constant {object}
   */
  const csLib = window.csLib;

  /**
   * API endpoint for the auto-caption web service.
   * @constant {string}
   */
  const API_ENDPOINT = "http://auto-caption-web:8000/auto-caption";

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
   * Retrieves the tags associated with a given scene ID.
   *
   * @param {string} scene_id - The ID of the scene to retrieve tags for.
   * @returns {Promise<object[]>} - A promise that resolves with an array of tag objects.
   */
  async function getTagsForScene(scene_id) {
    const reqData = {
      query: `{
        findScene(id: "${scene_id}") {
          tags {
            id
          }
        }
      }`,
    };
    var result = await csLib.callGQL(reqData);
    return result.findScene.tags;
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
   * Scans the caption at the given path.
   *
   * @param {string} captionPath - The path of the caption to scan.
   * @returns {Promise<string>} - A promise that resolves with the job ID.
   */
  async function scanCaption(captionPath) {
    const captionParent = captionPath.substring(
      0,
      captionPath.lastIndexOf("/")
    );
    const reqData = {
      variables: { paths: [captionParent] },
      query: `mutation MetadataScan {
            metadataScan(
                input: {
                    paths: $paths, 
                }
            )
        }`,
    };
    var result = await csLib.callGQL(reqData);
    return result.metadataScan;
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
            }
        }`,
    };
    var result = await csLib.callGQL(reqData);
    return result;
  }

  /**
   * Waits for a job with the given job ID to finish.
   *
   * @param {string} jobId - The ID of the job to wait for.
   * @returns {Promise<boolean>} - A promise that resolves when the job is finished.
   */
  async function awaitJobFinished(jobId) {
    return new Promise((resolve, reject) => {
      const interval = setInterval(async () => {
        const status = await getJobStatus(jobId).then(
          (data) => data.findJob?.status
        );
        // console.log(`Job status: ${status}`)
        if (status === "FINISHED") {
          clearInterval(interval);
          resolve(true);
        } else if (status === "FAILED") {
          clearInterval(interval);
          reject(new Error("Job failed"));
        }
      }, 100);
    });
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
        player.textTracks().getTrackById(lang).mode = "showing";
        return true;
      }
    }
    return false;
  }

  /**
   * Processes the remote caption for a given scene language and video path.
   *
   * @param {string} scene_id - The ID of the scene to process the caption for.
   * @param {string} sceneLanguage - The language of the scene.
   * @param {string} videoPath - The path of the video file.
   * @returns {Promise<boolean>} - A promise that resolves when the caption processing is complete.
   */
  async function processRemoteCaption(scene_id, sceneLanguage, videoPath) {
    if (!sceneLanguage || !videoPath) return false;
    return fetch(API_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        video_path: videoPath,
        language: LANG_DICT[sceneLanguage],
        translate_to: LANG_DICT["English"],
      }),
    }).then(async (response) => {
      if (response.ok) {
        const captionData = await response.json(),
          captionPath = captionData.file_path;
        if (captionPath) {
          scanCaption(captionPath)
            .then(async (jobId) => awaitJobFinished(jobId))
            .then(async () => {
              const captionUrl = await getCaptionForScene(scene_id);
              if (captionUrl) {
                return loadPlayerCaption(captionUrl);
              }
            })
            .catch((error) => {
              console.error("Error scanning caption:", error);
              return false;
            });
        } else {
          console.error("No caption path returned from API.");
          return false;
        }
      } else {
        console.error(
          "Error from auto-caption API:",
          response.status,
          response.statusText
        );
        return false;
      }
    });
  }

  /**
   * Detects the foreign language of a scene based on its tags.
   *
   * @param {string} scene_id - The ID of the scene to detect the language for.
   * @returns {Promise<string|null>} - A promise that resolves with the detected language or null if not found.
   */
  async function detectForeignLanguage(scene_id) {
    const sceneTags = await getTagsForScene(scene_id);
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

  csLib.PathElementListener("/scenes/", ".video-wrapper", async function (el) {
    const [_, scene_id] = getScenarioAndID();
    const scene = await getScene(scene_id);
    const videoPath = scene?.files[0]?.path;
    try {
      const sceneLanguage = await detectForeignLanguage(scene_id);
      if (sceneLanguage && videoPath) {
        processRemoteCaption(scene_id, sceneLanguage, videoPath).catch(
          (error) => {
            console.error("Error processing remote caption:", error);
          }
        );
      } else {
        // console.log("No foreign language tag detected for this scene.");
      }
    } catch (error) {
      console.error("Error detecting foreign language:", error);
    }
  });
})();
