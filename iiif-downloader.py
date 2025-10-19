import argparse
import json
import os
import requests
from urllib.parse import urlparse

def download_iiif_images(manifest_data, size=None, output_folder=None, resume=False):
    # Headers to mimic a browser
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }

    # Determine output directory
    if output_folder:
        base_filename = output_folder
    else:
        # Extract the base filename
        if 'filename' in manifest_data:
            base_filename = os.path.splitext(manifest_data['filename'])[0]
        else:
            base_filename = 'iiif_images'

    # Create a directory to store the downloaded images
    os.makedirs(base_filename, exist_ok=True)

    manifest = manifest_data['content']
    canvases = manifest['sequences'][0]['canvases']
    total_images = len(canvases)
    
    # Count existing files if resume is enabled
    existing_files = 0
    if resume:
        for idx in range(total_images):
            filename = f"{base_filename}/image_{idx+1:03d}.jpg"
            if os.path.exists(filename):
                existing_files += 1
    
    print(f"Total images to process: {total_images}")
    if resume and existing_files > 0:
        print(f"Found {existing_files} existing files, will skip them")
        print(f"Will download {total_images - existing_files} remaining images")

    # Iterate through the canvases in the manifest
    for idx, canvas in enumerate(canvases):
        try:
            image_info_url = canvas['images'][0]['resource']['service']['@id'] + '/info.json'
            print(f"Fetching image info from: {image_info_url}")
            
            # Fetch image info
            response = requests.get(image_info_url, headers=headers)
            response.raise_for_status()  # Raise an exception for bad status codes
            
            # Check if the content type is JSON
            content_type = response.headers.get('Content-Type', '')
            if 'application/json' not in content_type.lower():
                print(f"Warning: The image info response doesn't seem to be JSON. Content-Type: {content_type}")
                print("Response content:")
                print(response.text[:500])  # Print first 500 characters of the response
                continue  # Skip to the next image

            # Try to parse JSON
            try:
                info = json.loads(response.text)
            except json.JSONDecodeError as e:
                print(f"Error decoding image info JSON: {e}")
                print("Response content:")
                print(response.text[:500])  # Print first 500 characters of the response
                continue  # Skip to the next image

            # Determine the size to use
            if size:
                image_size = size
            else:
                # Use the largest available size
                image_size = max(info['sizes'], key=lambda x: x['width'])['width']

            # Construct the image URL
            image_url = f"{info['@id']}/full/{image_size},/0/default.jpg"

            filename = f"{base_filename}/image_{idx+1:03d}.jpg"
            
            # Check if file already exists and resume is enabled
            if resume and os.path.exists(filename):
                print(f"Skipping existing file: {filename}")
                continue

            # Download the image
            print(f"Downloading image {idx+1}/{total_images} from: {image_url}")
            response = requests.get(image_url, headers=headers)
            response.raise_for_status()

            with open(filename, 'wb') as f:
                f.write(response.content)
            print(f"Downloaded: {filename}")

        except requests.RequestException as e:
            print(f"Error downloading image {idx+1}: {e}")
        except KeyError as e:
            print(f"Error accessing manifest data for image {idx+1}: {e}")
        except Exception as e:
            print(f"Unexpected error processing image {idx+1}: {e}")


def save_metadata(manifest_data, output_folder=None):
    """Extract and save metadata from the IIIF manifest to a text file."""
    manifest = manifest_data['content']
    
    # Determine output directory
    if output_folder:
        base_filename = output_folder
    else:
        if 'filename' in manifest_data:
            base_filename = os.path.splitext(manifest_data['filename'])[0]
        else:
            base_filename = 'iiif_images'
    
    # Create output directory if it doesn't exist
    os.makedirs(base_filename, exist_ok=True)
    
    metadata_file = os.path.join(base_filename, 'metadata.txt')
    
    with open(metadata_file, 'w', encoding='utf-8') as f:
        f.write("IIIF Manifest Metadata\n")
        f.write("=" * 50 + "\n\n")
        
        # Basic manifest information
        if 'label' in manifest:
            f.write(f"Title: {manifest['label']}\n")
        if 'description' in manifest:
            f.write(f"Description: {manifest['description']}\n")
        if '@id' in manifest:
            f.write(f"Manifest ID: {manifest['@id']}\n")
        if 'attribution' in manifest:
            f.write(f"Attribution: {manifest['attribution']}\n")
        if 'license' in manifest:
            f.write(f"License: {manifest['license']}\n")
        
        f.write("\n")
        
        # Sequence information
        if 'sequences' in manifest and manifest['sequences']:
            sequence = manifest['sequences'][0]
            if 'label' in sequence:
                f.write(f"Sequence: {sequence['label']}\n")
            
            # Canvas count
            if 'canvases' in sequence:
                f.write(f"Number of pages/canvases: {len(sequence['canvases'])}\n")
                
                # Canvas details
                f.write("\nCanvas Details:\n")
                f.write("-" * 30 + "\n")
                for idx, canvas in enumerate(sequence['canvases']):
                    f.write(f"\nCanvas {idx + 1}:\n")
                    if 'label' in canvas:
                        f.write(f"  Label: {canvas['label']}\n")
                    if 'width' in canvas and 'height' in canvas:
                        f.write(f"  Dimensions: {canvas['width']} x {canvas['height']}\n")
                    if 'images' in canvas and canvas['images']:
                        image = canvas['images'][0]
                        if 'resource' in image and 'service' in image['resource']:
                            service_id = image['resource']['service']['@id']
                            f.write(f"  Image service: {service_id}\n")
        
        # Metadata section if available
        if 'metadata' in manifest:
            f.write("\nAdditional Metadata:\n")
            f.write("-" * 30 + "\n")
            for item in manifest['metadata']:
                if 'label' in item and 'value' in item:
                    f.write(f"{item['label']}: {item['value']}\n")
        
        # Rights information
        if 'rights' in manifest:
            f.write(f"\nRights: {manifest['rights']}\n")
        
        # Viewing direction
        if 'viewingDirection' in manifest:
            f.write(f"Viewing Direction: {manifest['viewingDirection']}\n")
        
        # Viewing hint
        if 'viewingHint' in manifest:
            f.write(f"Viewing Hint: {manifest['viewingHint']}\n")
    
    print(f"Metadata saved to: {metadata_file}")


def load_manifest(source):
    if source.startswith('http://') or source.startswith('https://'):
        # It's a URL
        try:
            response = requests.get(source)
            response.raise_for_status()
            content = json.loads(response.text)
            return {'content': content, 'filename': os.path.basename(urlparse(source).path)}
        except requests.RequestException as e:
            print(f"Error fetching the manifest: {e}")
            return None
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON from URL: {e}")
            return None
    else:
        # It's a local file
        try:
            with open(source, 'r') as file:
                content = json.load(file)
            return {'content': content, 'filename': os.path.basename(source)}
        except FileNotFoundError:
            print(f"File not found: {source}")
            return None
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON from file: {e}")
            return None

def main():
    parser = argparse.ArgumentParser(description="Download IIIF images from a manifest URL or local file.")
    parser.add_argument("--source", required=True, help="URL or file path of the IIIF manifest")
    parser.add_argument("--size", type=int, help="Desired image width (optional)")
    parser.add_argument("--output", help="Output folder for images (optional)")
    parser.add_argument("--metadata", action="store_true", help="Save manifest metadata to a text file")
    parser.add_argument("--resume", action="store_true", help="Resume interrupted downloads by skipping existing files")
    args = parser.parse_args()

    manifest_data = load_manifest(args.source)
    if manifest_data:
        # Save metadata if requested
        if args.metadata:
            save_metadata(manifest_data, args.output)
        
        # Download images
        download_iiif_images(manifest_data, args.size, args.output, args.resume)

if __name__ == "__main__":
    main()
    