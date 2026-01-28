#!/usr/bin/env node

/**
 * Build OpenAPI bundles that include the API version number.
 * 
 * The API version is specified using the custom extension `x-github-api-versions`
 * in the OpenAPI info section.
 * 
 * Usage:
 *   node scripts/build-versioned-bundles.js [options]
 * 
 * Options:
 *   --input <dir>      Input directory containing OpenAPI descriptions (default: descriptions)
 *   --output <dir>     Output directory for versioned bundles (default: output)
 *   --releases <list>  Comma-separated list of releases to process (default: all)
 *   --versions <list>  Comma-separated list of API versions to include
 *   --format <format>  Output format: json, yaml, or both (default: both)
 */

const fs = require('fs');
const path = require('path');

// Try to load js-yaml for YAML support
let yaml;
try {
  yaml = require('js-yaml');
} catch {
  yaml = null;
}

// Parse command line arguments
function parseArgs() {
  const args = process.argv.slice(2);
  const options = {
    input: 'descriptions',
    output: 'output',
    releases: null,
    versions: null,
    format: 'both'
  };

  for (let i = 0; i < args.length; i++) {
    switch (args[i]) {
      case '--input':
        options.input = args[++i];
        break;
      case '--output':
        options.output = args[++i];
        break;
      case '--releases':
        options.releases = args[++i]?.split(',').map(s => s.trim());
        break;
      case '--versions':
        options.versions = args[++i]?.split(',').map(s => s.trim());
        break;
      case '--format':
        options.format = args[++i];
        break;
      case '--help':
      case '-h':
        console.log(`
Build OpenAPI bundles that include the API version number.

Usage:
  node scripts/build-versioned-bundles.js [options]

Options:
  --input <dir>      Input directory containing OpenAPI descriptions (default: descriptions)
  --output <dir>     Output directory for versioned bundles (default: output)
  --releases <list>  Comma-separated list of releases to process (default: all)
  --versions <list>  Comma-separated list of API versions to include
  --format <format>  Output format: json, yaml, or both (default: both)
  --help, -h         Show this help message

Examples:
  # Build all releases with default versions
  node scripts/build-versioned-bundles.js

  # Build only api.github.com release
  node scripts/build-versioned-bundles.js --releases api.github.com

  # Build with specific API version
  node scripts/build-versioned-bundles.js --versions 2022-11-28

  # Output to custom directory
  node scripts/build-versioned-bundles.js --output ./versioned-bundles
        `);
        process.exit(0);
    }
  }

  return options;
}

// Get all available releases from the descriptions directory
function getAvailableReleases(inputDir) {
  const releases = [];
  
  if (!fs.existsSync(inputDir)) {
    console.error(`Error: Input directory "${inputDir}" does not exist`);
    process.exit(1);
  }

  const entries = fs.readdirSync(inputDir, { withFileTypes: true });
  
  for (const entry of entries) {
    if (entry.isDirectory()) {
      releases.push(entry.name);
    }
  }

  return releases;
}

// Find OpenAPI files for a release
function findOpenAPIFiles(releaseDir) {
  const files = {
    base: null,
    versioned: []
  };

  if (!fs.existsSync(releaseDir)) {
    return files;
  }

  const entries = fs.readdirSync(releaseDir);
  
  for (const entry of entries) {
    // Skip directories (like dereferenced/)
    const fullPath = path.join(releaseDir, entry);
    if (fs.statSync(fullPath).isDirectory()) continue;

    // Match patterns like api.github.com.json or ghes-3.16.2022-11-28.json
    const jsonMatch = entry.match(/^(.+?)(?:\.(\d{4}-\d{2}-\d{2}))?\.json$/);
    const yamlMatch = entry.match(/^(.+?)(?:\.(\d{4}-\d{2}-\d{2}))?\.yaml$/);

    if (jsonMatch) {
      const [, base, version] = jsonMatch;
      if (version) {
        files.versioned.push({ path: fullPath, version, format: 'json', base });
      } else if (!files.base || entry.endsWith('.json')) {
        files.base = { path: fullPath, format: 'json', name: base };
      }
    } else if (yamlMatch && !files.base) {
      const [, base, version] = yamlMatch;
      if (version) {
        files.versioned.push({ path: fullPath, version, format: 'yaml', base });
      } else {
        files.base = { path: fullPath, format: 'yaml', name: base };
      }
    }
  }

  return files;
}

// Load and parse OpenAPI document
function loadOpenAPIDocument(filePath) {
  const content = fs.readFileSync(filePath, 'utf8');
  
  if (filePath.endsWith('.json')) {
    return JSON.parse(content);
  } else if (filePath.endsWith('.yaml') || filePath.endsWith('.yml')) {
    if (yaml) {
      return yaml.load(content);
    } else {
      console.warn(`Warning: js-yaml not installed. Run 'npm install' to enable YAML support.`);
      return null;
    }
  }
  
  return null;
}

// Add x-github-api-versions to the OpenAPI document
function addApiVersion(doc, apiVersion) {
  if (!doc || !doc.info) return doc;

  // Clone the document to avoid mutating the original
  const newDoc = JSON.parse(JSON.stringify(doc));

  // Add or update the x-github-api-versions extension
  if (!newDoc.info['x-github-api-versions']) {
    newDoc.info['x-github-api-versions'] = [];
  }

  if (!newDoc.info['x-github-api-versions'].includes(apiVersion)) {
    newDoc.info['x-github-api-versions'].push(apiVersion);
  }

  // Sort versions in descending order (newest first)
  newDoc.info['x-github-api-versions'].sort((a, b) => b.localeCompare(a));

  return newDoc;
}

// Extract API version from filename or content
function extractApiVersion(filePath, doc) {
  // Try to extract from filename (e.g., api.github.com.2022-11-28.json)
  const filenameMatch = path.basename(filePath).match(/\.(\d{4}-\d{2}-\d{2})\./);
  if (filenameMatch) {
    return filenameMatch[1];
  }

  // Try to extract from document
  if (doc?.info?.['x-github-api-versions']?.length > 0) {
    return doc.info['x-github-api-versions'][0];
  }

  // Default to the current supported version
  return '2022-11-28';
}

// Write OpenAPI document to file
function writeOpenAPIDocument(doc, outputPath, format) {
  const dir = path.dirname(outputPath);
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }

  if (format === 'json') {
    fs.writeFileSync(outputPath, JSON.stringify(doc, null, 2));
  } else if (format === 'yaml') {
    if (yaml) {
      fs.writeFileSync(outputPath, yaml.dump(doc, { 
        lineWidth: -1,  // Don't wrap lines
        noRefs: true,   // Don't use YAML references
        sortKeys: false // Preserve key order
      }));
    } else {
      console.warn(`YAML output requires js-yaml package. Writing as JSON instead.`);
      fs.writeFileSync(outputPath.replace('.yaml', '.json'), JSON.stringify(doc, null, 2));
    }
  }
}

// Generate output filename with API version
function generateOutputFilename(release, apiVersion, format) {
  return `${release}.${apiVersion}.${format}`;
}

// Process a single release
function processRelease(releaseName, releaseDir, outputDir, options) {
  console.log(`\nProcessing release: ${releaseName}`);
  
  const files = findOpenAPIFiles(releaseDir);
  
  if (!files.base && files.versioned.length === 0) {
    console.log(`  No OpenAPI files found for ${releaseName}`);
    return;
  }

  // Determine which API versions to process
  let apiVersions = options.versions || [];
  
  // If no versions specified, extract from existing versioned files
  if (apiVersions.length === 0 && files.versioned.length > 0) {
    apiVersions = [...new Set(files.versioned.map(f => f.version))];
  }
  
  // If still no versions, use default
  if (apiVersions.length === 0) {
    apiVersions = ['2022-11-28'];
  }

  console.log(`  API versions: ${apiVersions.join(', ')}`);

  // Process each API version
  for (const apiVersion of apiVersions) {
    // Find source file - prefer versioned file if it exists
    const versionedFile = files.versioned.find(f => f.version === apiVersion);
    const sourceFile = versionedFile || files.base;
    
    if (!sourceFile) {
      console.log(`  Skipping version ${apiVersion}: no source file`);
      continue;
    }

    console.log(`  Processing version: ${apiVersion} from ${path.basename(sourceFile.path)}`);

    // Load the document
    const doc = loadOpenAPIDocument(sourceFile.path);
    if (!doc) {
      console.log(`  Error loading ${sourceFile.path}`);
      continue;
    }

    // Add API version to the document
    const versionedDoc = addApiVersion(doc, apiVersion);

    // Write output files
    const releaseOutputDir = path.join(outputDir, releaseName);

    if (options.format === 'json' || options.format === 'both') {
      const jsonPath = path.join(releaseOutputDir, generateOutputFilename(releaseName, apiVersion, 'json'));
      writeOpenAPIDocument(versionedDoc, jsonPath, 'json');
      console.log(`    Created: ${jsonPath}`);
    }

    if (options.format === 'yaml' || options.format === 'both') {
      const yamlPath = path.join(releaseOutputDir, generateOutputFilename(releaseName, apiVersion, 'yaml'));
      if (yaml) {
        writeOpenAPIDocument(versionedDoc, yamlPath, 'yaml');
        console.log(`    Created: ${yamlPath}`);
      } else {
        console.log(`    YAML output requires js-yaml package (skipped): ${yamlPath}`);
      }
    }
  }

  // Also copy base files if they exist and are different from versioned
  if (files.base) {
    const doc = loadOpenAPIDocument(files.base.path);
    if (doc) {
      const baseOutputDir = path.join(outputDir, releaseName);
      if (options.format === 'json' || options.format === 'both') {
        const jsonPath = path.join(baseOutputDir, `${releaseName}.json`);
        
        // Ensure x-github-api-versions is present even in base
        const enhancedDoc = addApiVersion(doc, apiVersions[0] || '2022-11-28');
        writeOpenAPIDocument(enhancedDoc, jsonPath, 'json');
        console.log(`    Created base: ${jsonPath}`);
      }
    }
  }
}

// Main function
function main() {
  const options = parseArgs();
  
  console.log('OpenAPI Versioned Bundle Builder');
  console.log('=================================');
  console.log(`Input directory: ${options.input}`);
  console.log(`Output directory: ${options.output}`);

  // Get list of releases to process
  let releases;
  if (options.releases) {
    releases = options.releases;
  } else {
    releases = getAvailableReleases(options.input);
  }

  console.log(`Releases to process: ${releases.join(', ')}`);

  // Create output directory
  if (!fs.existsSync(options.output)) {
    fs.mkdirSync(options.output, { recursive: true });
  }

  // Process each release
  for (const release of releases) {
    const releaseDir = path.join(options.input, release);
    processRelease(release, releaseDir, options.output, options);
  }

  console.log('\n✓ Build complete!');
}

main();
