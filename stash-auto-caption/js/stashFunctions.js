(async () => {
  "use strict";

  const csLib = window.csLib;

  /**
   * Waits for an element with the specified ID to be available in the DOM, then executes a callback function.
   *
   * @param {string} elementId - The ID of the element to wait for.
   * @param {function} callBack - The callback function to execute once the element is found. Receives the elementId and the element as arguments.
   * @param {number} [time=100] - The interval time in milliseconds to wait before checking for the element again.
   */
  function waitForElementId(elementId, callBack, time) {
    time = typeof time !== "undefined" ? time : 100;
    window.setTimeout(() => {
      const element = document.getElementById(elementId);
      if (element) {
        callBack(elementId, element);
      } else {
        waitForElementId(elementId, callBack);
      }
    }, time);
  }

  /**
   * Waits for an element with the specified class name to appear in the DOM, then executes a callback function.
   *
   * @param {string} elementId - The class name of the element to wait for.
   * @param {function} callBack - The callback function to execute once the element is found. Receives the elementId and the found element(s) as arguments.
   * @param {number} [time=100] - The interval time in milliseconds to wait before checking for the element again.
   */
  function waitForElementClass(elementId, callBack, time) {
    time = typeof time !== "undefined" ? time : 100;
    window.setTimeout(() => {
      const element = document.getElementsByClassName(elementId);
      if (element.length > 0) {
        callBack(elementId, element);
      } else {
        waitForElementClass(elementId, callBack);
      }
    }, time);
  }

  /**
   * Waits for an element to appear in the DOM based on the provided XPath and then executes a callback function.
   *
   * @param {string} xpath - The XPath of the element to wait for.
   * @param {function} callBack - The callback function to execute once the element is found. The callback receives the XPath and the found element as arguments.
   * @param {number} [time=100] - The interval time in milliseconds to wait before checking for the element again. Defaults to 100 milliseconds if not provided.
   */
  function waitForElementByXpath(xpath, callBack, time) {
    time = typeof time !== "undefined" ? time : 100;
    window.setTimeout(() => {
      const element = getElementByXpath(xpath);
      if (element) {
        callBack(xpath, element);
      } else {
        waitForElementByXpath(xpath, callBack);
      }
    }, time);
  }

  /**
   * Waits for elements to be available in the DOM based on the provided XPath and executes a callback function when they are found.
   *
   * @param {string} xpath - The XPath expression to locate the elements.
   * @param {function} callBack - The callback function to execute when the elements are found. It receives the XPath and the found elements as arguments.
   * @param {number} [time=100] - The interval time in milliseconds to wait before checking for the elements again.
   */
  function waitForElementsByXpath(xpath, callBack, time) {
    time = typeof time !== "undefined" ? time : 100;
    window.setTimeout(() => {
      const element = getElementsByXpath(xpath);
      if (element) {
        callBack(xpath, element);
      } else {
        waitForElementsByXpath(xpath, callBack);
      }
    }, time);
  }

  /**
   * Retrieves a single DOM element based on the provided XPath expression.
   *
   * @param {string} xpath - The XPath expression to locate the element.
   * @param {Node} [contextNode=document] - The context node to start the search from. Defaults to the document root if not provided.
   * @returns {Node|null} The first DOM element that matches the XPath expression, or null if no match is found.
   */
  function getElementByXpath(xpath, contextNode) {
    return document.evaluate(
      xpath,
      contextNode || document,
      null,
      XPathResult.FIRST_ORDERED_NODE_TYPE,
      null
    ).singleNodeValue;
  }

  /**
   * Retrieves elements from the document based on the provided XPath expression.
   *
   * @param {string} xpath - The XPath expression to evaluate.
   * @param {Node} [contextNode=document] - The context node for the XPath evaluation. Defaults to the document if not provided.
   * @returns {XPathResult} An ordered node iterator containing the nodes that match the XPath expression.
   */
  function getElementsByXpath(xpath, contextNode) {
    return document.evaluate(
      xpath,
      contextNode || document,
      null,
      XPathResult.ORDERED_NODE_ITERATOR_TYPE,
      null
    );
  }

  /**
   * Finds the closest ancestor of an element that matches a given selector.
   *
   * @param {Element} el - The element from which to start the search.
   * @param {string} selector - The CSS selector to match the ancestor against.
   * @param {string} [stopSelector] - An optional CSS selector to stop the search if matched.
   * @returns {Element|null} The closest ancestor element that matches the selector, or null if no match is found.
   */
  function getClosestAncestor(el, selector, stopSelector) {
    let retval = null;
    while (el) {
      if (el.matches(selector)) {
        retval = el;
        break;
      } else if (stopSelector && el.matches(stopSelector)) {
        break;
      }
      el = el.parentElement;
    }
    return retval;
  }

  /**
   * Inserts a new node after an existing node in the DOM.
   *
   * @param {Node} newNode - The new node to be inserted.
   * @param {Node} existingNode - The existing node after which the new node will be inserted.
   */
  function insertAfter(newNode, existingNode) {
    existingNode.parentNode.insertBefore(newNode, existingNode.nextSibling);
  }

  /**
   * Creates a DOM element from an HTML string.
   *
   * @param {string} htmlString - The HTML string to convert into a DOM element.
   * @returns {Element} The first child element created from the HTML string.
   */
  function createElementFromHTML(htmlString) {
    const div = document.createElement("div");
    div.innerHTML = htmlString.trim();
    return div.firstChild;
  }

  /**
   * Sets the value of a native HTML element, ensuring that any associated
   * event listeners are triggered.
   *
   * @param {HTMLElement} element - The HTML element whose value is to be set.
   * @param {string} value - The value to set on the element.
   */
  function setNativeValue(element, value) {
    const valueSetter = Object.getOwnPropertyDescriptor(element, "value").set;
    const prototype = Object.getPrototypeOf(element);
    const prototypeValueSetter = Object.getOwnPropertyDescriptor(
      prototype,
      "value"
    ).set;

    if (valueSetter && valueSetter !== prototypeValueSetter) {
      prototypeValueSetter.call(element, value);
    } else {
      valueSetter.call(element, value);
    }
  }

  /**
   * Updates the value of a text input element and dispatches an input event.
   *
   * @param {HTMLElement} element - The text input element to update.
   * @param {string} value - The new value to set on the text input element.
   */
  function updateTextInput(element, value) {
    setNativeValue(element, value);
    element.dispatchEvent(new Event("input", { bubbles: true }));
  }

  /**
   * Concatenates two regular expressions into a single regular expression.
   *
   * @param {RegExp} reg - The first regular expression.
   * @param {RegExp} exp - The second regular expression.
   * @returns {RegExp} A new regular expression that is the concatenation of the two input regular expressions, with combined flags.
   */
  function concatRegexp(reg, exp) {
    let flags = reg.flags + exp.flags;
    flags = Array.from(new Set(flags.split(""))).join();
    return new RegExp(reg.source + exp.source, flags);
  }

  /**
   * Sorts the child elements of a given node in place based on their innerHTML content.
   *
   * @param {Node} node - The parent node whose child elements will be sorted.
   */
  function sortElementChildren(node) {
    const items = node.childNodes;
    const itemsArr = [];
    for (const i in items) {
      if (items[i].nodeType == Node.ELEMENT_NODE) {
        // get rid of the whitespace text nodes
        itemsArr.push(items[i]);
      }
    }

    itemsArr.sort((a, b) => {
      return a.innerHTML == b.innerHTML
        ? 0
        : a.innerHTML > b.innerHTML
        ? 1
        : -1;
    });

    for (let i = 0; i < itemsArr.length; i++) {
      node.appendChild(itemsArr[i]);
    }
  }

  /**
   * Converts an XPathResult to an array of nodes.
   *
   * @param {XPathResult} result - The XPathResult to convert.
   * @returns {Node[]} An array of nodes extracted from the XPathResult.
   */
  function xPathResultToArray(result) {
    let node = null;
    const nodes = [];
    while ((node = result.iterateNext())) {
      nodes.push(node);
    }
    return nodes;
  }

  /**
   * Reloads an image by fetching it with no cache and updating the source of all matching images in the document.
   *
   * @param {string} url - The URL of the image to reload.
   * @returns {Promise<void>} A promise that resolves when the image has been reloaded.
   */
  function reloadImg(url) {
    return fetch(url, { cache: "reload", mode: "no-cors" }).then(() =>
      document.body
        .querySelectorAll(`img[src='${url}']`)
        .forEach((img) => (img.src = url))
    );
  }

  /**
   * Runs a specified task for a given plugin.
   *
   * @param {string} pluginId - The ID of the plugin.
   * @param {string} taskName - The name of the task to run.
   * @param {Array} [args=[]] - Optional arguments for the task.
   * @returns {Promise} - A promise that resolves with the result of the GraphQL mutation.
   */
  async function runPluginTask(pluginId, taskName, args = []) {
    const reqData = {
      operationName: "RunPluginTask",
      variables: {
        plugin_id: pluginId,
        task_name: taskName,
        args: args,
      },
      query:
        "mutation RunPluginTask($plugin_id: ID!, $task_name: String!, $args: [PluginArgInput!]) {\n  runPluginTask(plugin_id: $plugin_id, task_name: $task_name, args: $args)\n}\n",
    };
    return csLib.callGQL(reqData);
  }

  /**
   * Fetches the list of plugins with their details including tasks and hooks.
   *
   * @async
   * @function getPlugins
   * @returns {Promise<Object>} A promise that resolves to the response of the GraphQL query for plugins.
   * @property {Array} plugins - The list of plugins.
   * @property {string} plugins.id - The ID of the plugin.
   * @property {string} plugins.name - The name of the plugin.
   * @property {string} plugins.description - The description of the plugin.
   * @property {string} plugins.url - The URL of the plugin.
   * @property {string} plugins.version - The version of the plugin.
   * @property {Array} plugins.tasks - The tasks associated with the plugin.
   * @property {string} plugins.tasks.name - The name of the task.
   * @property {string} plugins.tasks.description - The description of the task.
   * @property {Array} plugins.hooks - The hooks associated with the plugin.
   * @property {string} plugins.hooks.name - The name of the hook.
   * @property {string} plugins.hooks.description - The description of the hook.
   * @property {Array} plugins.hooks.hooks - The hooks of the hook.
   */
  async function getPlugins() {
    const reqData = {
      operationName: "Plugins",
      variables: {},
      query: `query Plugins {
          plugins {
            id
            name
            description
            url
            version
            tasks {
              name
              description
              __typename
            }
            hooks {
              name
              description
              hooks
            }
          }
          }
          `,
    };
    return csLib.callGQL(reqData);
  }

  /**
   * Fetches the configuration for stash boxes.
   *
   * This function sends a GraphQL query to retrieve the configuration details
   * for stash boxes, including the endpoint, API key, and name.
   *
   * @returns {Promise<Object>} A promise that resolves to the response from the GraphQL call,
   * containing the stash boxes configuration.
   */
  async function getStashBoxes() {
    const reqData = {
      operationName: "Configuration",
      variables: {},
      query: `query Configuration {
                      configuration {
                        general {
                          stashBoxes {
                            endpoint
                            api_key
                            name
                          }
                        }
                      }
                    }`,
    };
    return csLib.callGQL(reqData);
  }

  /**
   * Fetches the API key from the configuration using a GraphQL query.
   *
   * @returns {Promise<Object>} A promise that resolves to the response of the GraphQL call, which includes the API key.
   */
  async function getApiKey() {
    const reqData = {
      operationName: "Configuration",
      variables: {},
      query: `query Configuration {
                      configuration {
                        general {
                          apiKey
                        }
                      }
                    }`,
    };
    return csLib.callGQL(reqData);
  }

  /**
   * Fetches the configuration of plugins.
   *
   * This function sends a GraphQL request to retrieve the configuration
   * details, specifically the plugins, from the server.
   *
   * @returns {Promise<Object>} A promise that resolves to the configuration object containing the plugins.
   */
  async function getPluginConfigs() {
    const reqData = {
      operationName: "Configuration",
      variables: {},
      query: `query Configuration {
                      configuration {
                        plugins
                      }
                    }`,
    };
    return csLib.callGQL(reqData);
  }

  /**
   * Retrieves the configuration for a specific plugin.
   *
   * @param {string} pluginId - The unique identifier of the plugin.
   * @returns {Promise<Object>} A promise that resolves to the plugin configuration object.
   */
  async function getPluginConfig(pluginId) {
    const data = await getPluginConfigs();
    return data.configuration.plugins[pluginId];
  }

  /**
   * Updates the configuration of a plugin.
   *
   * @param {string} pluginId - The ID of the plugin to configure.
   * @param {Object} config - The configuration settings to apply to the plugin.
   * @returns {Promise<Object>} - A promise that resolves to the response of the GraphQL mutation.
   */
  async function updatePluginConfig(pluginId, config) {
    const reqData = {
      operationName: "ConfigurePlugin",
      variables: {
        plugin_id: pluginId,
        input: config,
      },
      query: `mutation ConfigurePlugin($plugin_id: ID!, $input: Map!) {
                      configurePlugin(plugin_id: $plugin_id, input: $input)
                    }`,
    };
    return csLib.callGQL(reqData);
  }

  /**
   * Fetches the UI configuration by making a GraphQL query.
   *
   * @async
   * @function getUIConfig
   * @returns {Promise<Object>} A promise that resolves to the UI configuration object.
   */
  async function getUIConfig() {
    const reqData = {
      operationName: "Configuration",
      variables: {},
      query: `query Configuration {
                      configuration {
                        ui
                      }
                    }`,
    };
    return csLib.callGQL(reqData);
  }

  /**
   * Checks if the given URL location matches the specified fragment.
   *
   * @param {Location} location - The location object representing the URL to be checked.
   * @param {string} fragment - The fragment to match against the URL.
   * @returns {boolean} - Returns true if the URL matches the fragment, otherwise false.
   */
  function matchUrl(location, fragment) {
    const regexp = concatRegexp(new RegExp(location.origin), fragment);
    return location.href.match(regexp) != null;
  }

  /**
   * Polls logs for a specific message prefix and returns the message content.
   *
   * This function sends a GraphQL query to retrieve logs and checks if any log
   * message starts with the specified prefix. It retries the request with an
   * exponential backoff strategy until it finds the message or exceeds the
   * maximum number of retries.
   *
   * @param {string} prefix - The prefix of the log message to search for.
   * @returns {Promise<string>} - A promise that resolves to the log message content without the prefix.
   * @throws {Error} - Throws an error if the message is not found after the maximum number of retries.
   */
  async function pollLogsForMessage(prefix) {
    const reqTime = Date.now();
    const reqData = {
      variables: {},
      query: `query Logs {
                      logs {
                          time
                          level
                          message
                      }
                  }`,
    };
    await new Promise((r) => setTimeout(r, 500));
    let retries = 0;
    while (true) {
      const delay = 2 ** retries * 100;
      await new Promise((r) => setTimeout(r, delay));
      retries++;

      const logs = await csLib.callGQL(reqData);
      for (const log of logs.logs) {
        const logTime = Date.parse(log.time);
        if (logTime > reqTime && log.message.startsWith(prefix)) {
          return log.message.replace(prefix, "").trim();
        }
      }

      if (retries >= 5) {
        throw `Poll logs failed for message: ${prefix}`;
      }
    }
  }

  /**
   * Updates the progress bar's width and visibility based on the given value.
   *
   * @param {number} value - The progress value as a percentage (0-100).
   *                         If the value is less than or equal to 0 or greater than 100,
   *                         the progress bar will be hidden.
   */
  function setProgress(value) {
    const progressBar = document.getElementById("progress-bar");
    if (progressBar) {
      progressBar.firstChild.style.width = value + "%";
      progressBar.style.display = value <= 0 || value > 100 ? "none" : "flex";
    }
  }

  /**
   * Parses a search item element and extracts relevant information.
   *
   * @param {HTMLElement} searchItem - The search item element to parse.
   * @param {Object} scenes - The scenes data object to retrieve additional information.
   * @returns {Object} An object containing the parsed information.
   * @returns {HTMLElement} return.urlNode - The anchor element containing the scene link.
   * @returns {URL} return.url - The URL object created from the scene link.
   * @returns {string} return.id - The ID extracted from the URL pathname.
   * @returns {Object} return.data - The scene data associated with the ID.
   * @returns {HTMLElement} return.nameNode - The div element containing the scene name.
   * @returns {string} return.name - The inner text of the nameNode.
   * @returns {HTMLInputElement} return.queryInput - The input element for the search query.
   * @returns {NodeList} return.performerNodes - A NodeList of elements containing performer tags.
   * @returns {NodeList} return.tagNodes - A NodeList of elements containing scene tags.
   */
  function parseSearchItem(searchItem, scenes) {
    scenes = scenes || {};
    const urlNode = searchItem.querySelector("a.scene-link");
    const url = new URL(urlNode.href);
    const id = url.pathname.replace("/scenes/", "");
    const data = scenes[id];
    const nameNode = searchItem.querySelector(
      "a.scene-link > div.TruncatedText"
    );
    const name = nameNode.innerText;
    const queryInput = searchItem.querySelector("input.text-input");
    const performerNodes = searchItem.querySelectorAll(
      ".performer-tag-container"
    );
    const tagNodes = searchItem.querySelectorAll(
      ".original-scene-details div.col.col-lg-6 > div > span.tag-item.badge.badge-secondary"
    );

    return {
      urlNode,
      url,
      id,
      data,
      nameNode,
      name,
      queryInput,
      performerNodes,
      tagNodes,
    };
  }

  /**
   * Parses a search result item and extracts relevant information.
   * @param {HTMLElement} searchResultItem - The search result item element to parse.
   * @param {Object} remoteData - An object containing remote scene data.
   * @returns {Object} An object containing parsed information from the search result item.
   * @returns {HTMLElement} return.remoteUrlNode - The anchor element containing the remote scene URL.
   * @returns {string} return.remoteId - The ID extracted from the remote scene URL.
   * @returns {URL|null} return.remoteUrl - The URL object created from the remote scene URL, or null if not available.
   * @returns {Object} return.remoteData - The remote scene data associated with the remoteId.
   * @returns {HTMLElement[]} return.urlNodes - An array of elements containing URLs from the scene details.
   * @returns {HTMLElement|null} return.detailsNode - The element containing the scene details, or null if not found.
   */
  function parseSearchResultItem(searchResultItem, remoteData) {
    const remoteUrlNode = searchResultItem.querySelector(
      ".scene-details .optional-field .optional-field-content a"
    );
    const remoteId = remoteUrlNode?.href.split("/").pop();
    const remoteUrl = remoteUrlNode?.href ? new URL(remoteUrlNode.href) : null;

    const sceneDetailNodes = searchResultItem.querySelectorAll(
      ".scene-details .optional-field .optional-field-content"
    );
    let urlNodes = [];
    let detailsNode = null;
    for (const sceneDetailNode of sceneDetailNodes) {
      for (const sceneDetailNodeChild of sceneDetailNode.childNodes) {
        let bIsUrlNode = false;
        if (remoteData?.urls) {
          for (const remoteDataUrl of remoteData.urls) {
            if (remoteDataUrl === sceneDetailNodeChild.innerText) {
              urlNodes.push(sceneDetailNodeChild);
              bIsUrlNode = true;
            }
          }
        }
        if (
          !bIsUrlNode &&
          remoteData?.details === sceneDetailNodeChild.textContent
        ) {
          detailsNode = sceneDetailNodeChild;
        }
      }
    }

    const imageNode = searchResultItem.querySelector(
      ".scene-image-container .optional-field .optional-field-content"
    );

    const metadataNode = searchResultItem.querySelector(".scene-metadata");
    const titleNode = metadataNode.querySelector(
      "h4 .optional-field .optional-field-content"
    );
    let dateNode;
    let studioCodeNode;
    let directorNode;
    for (const node of searchResultItem.querySelectorAll(
      "h5 .optional-field .optional-field-content"
    )) {
      if (node.innerText === remoteData.date) {
        dateNode = node;
      } else if (node.innerText === remoteData.code) {
        studioCodeNode = node;
      } else if (node.innerText === "Director: " + remoteData.director) {
        directorNode = node;
      }
    }

    const entityNodes = searchResultItem.querySelectorAll(".entity-name");
    let studioNode = null;
    const performerNodes = [];
    for (const entityNode of entityNodes) {
      if (entityNode.innerText.startsWith("Studio:")) {
        studioNode = entityNode;
      } else if (entityNode.innerText.startsWith("Performer:")) {
        performerNodes.push(entityNode);
      }
    }

    const matchNodes = searchResultItem.querySelectorAll(
      "div.col-lg-6 div.mt-2 div.row.no-gutters.my-2 span.ml-auto"
    );
    const matches = [];
    for (const matchNode of matchNodes) {
      let matchType = null;
      const entityNode = matchNode.parentElement.querySelector(".entity-name");

      const matchName = matchNode.querySelector(
        ".optional-field-content b"
      ).innerText;
      const matchStoredId = matchNode.querySelector("a").href.split("/").pop();
      const remoteName = entityNode.querySelector("b").innerText;

      let data;
      if (entityNode.innerText.startsWith("Performer:")) {
        matchType = "performer";
        if (remoteData) {
          data = remoteData.performers.find(
            (performer) => performer.stored_id === matchStoredId
          );
        }
      } else if (entityNode.innerText.startsWith("Studio:")) {
        matchType = "studio";
        if (remoteData) {
          data = remoteData.studio;
        }
      }

      matches.push({
        matchType,
        matchNode,
        entityNode,
        matchName,
        remoteName,
        data,
      });
    }

    const tagNodes = searchResultItem.querySelectorAll(
      "div.col-lg-6 div.mt-2 div div.form-group.row div.col-xl-12.col-sm-9 .react-select__multi-value"
    );
    const unmatchedTagNodes = searchResultItem.querySelectorAll(
      "div.col-lg-6 div.mt-2 span.tag-item.badge.badge-secondary"
    );

    return {
      remoteUrlNode,
      remoteId,
      remoteUrl,
      remoteData,
      urlNodes,
      detailsNode,
      imageNode,
      titleNode,
      dateNode,
      studioNode,
      performerNodes,
      matches,
      tagNodes,
      unmatchedTagNodes,
      studioCodeNode,
      directorNode,
    };
  }

  window.stashFunctions = {
    waitForElementId,
    waitForElementClass,
    waitForElementByXpath,
    waitForElementsByXpath,
    getElementByXpath,
    getElementsByXpath,
    getClosestAncestor,
    insertAfter,
    createElementFromHTML,
    setNativeValue,
    updateTextInput,
    sortElementChildren,
    xPathResultToArray,
    reloadImg,
    get serverUrl() {
      return window.location.origin;
    },
    runPluginTask,
    getPlugins,
    getStashBoxes,
    getApiKey,
    getPluginConfigs,
    getPluginConfig,
    updatePluginConfig,
    getUIConfig,
    matchUrl,
    pollLogsForMessage,
    setProgress,
    parseSearchItem,
    parseSearchResultItem,
  };
})();
