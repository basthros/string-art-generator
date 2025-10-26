"""
GPU Router for Flask + SocketIO with Real-Time Streaming
Routes requests between Home GPU and RunPod with automatic failover

NEW in this version:
- Supports SSE streaming from home GPU for real-time animation
- Relays new_line events to frontend during generation
"""

import requests
import logging
import json
from typing import Optional, Dict, Any, Tuple, Callable
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class GPURouter:
    def __init__(
        self,
        home_gpu_url: Optional[str],
        runpod_run_url: str,
        runpod_status_url: str,
        runpod_api_key: str,
        timeout: int = 10
    ):
        """
        Initialize GPU Router for Flask/SocketIO with streaming support
        
        Args:
            home_gpu_url: URL to home GPU (e.g., http://100.64.1.2:8001) or None to disable
            runpod_run_url: RunPod run endpoint
            runpod_status_url: RunPod status endpoint
            runpod_api_key: RunPod API key
            timeout: Request timeout in seconds
        """
        self.home_gpu_url = home_gpu_url.rstrip('/') if home_gpu_url else None
        self.runpod_run_url = runpod_run_url
        self.runpod_status_url = runpod_status_url
        self.runpod_api_key = runpod_api_key
        self.timeout = timeout
        
        # Health status
        self.home_gpu_available = False
        self.last_health_check = None
        
        # Statistics
        self.stats = {
            "home_requests": 0,
            "runpod_requests": 0,
            "home_failures": 0,
            "runpod_failures": 0,
            "total_requests": 0
        }
        
        if self.home_gpu_url:
            logger.info(f"🚀 GPU Router initialized with Home GPU: {self.home_gpu_url}")
        else:
            logger.info(f"🚀 GPU Router initialized (RunPod only)")
        
    def check_home_gpu_health(self) -> bool:
        """
        Check if home GPU is healthy and available
        
        Returns:
            bool: True if home GPU is healthy
        """
        if not self.home_gpu_url:
            return False
            
        try:
            # Don't verify SSL for Tailscale Funnel (self-signed certs)
            verify_ssl = not self.home_gpu_url.endswith('.ts.net')
            
            response = requests.get(
                f"{self.home_gpu_url}/health",
                timeout=3,
                verify=verify_ssl
            )
            
            if response.status_code == 200:
                data = response.json()
                self.home_gpu_available = (
                    data.get("gpu_available", False) and 
                    not data.get("gpu_busy", False)
                )
                self.last_health_check = datetime.now()
                
                if self.home_gpu_available:
                    logger.debug("✅ Home GPU is healthy and available")
                    return True
                else:
                    logger.debug("⏳ Home GPU is busy or unavailable")
                    return False
            else:
                logger.warning(f"⚠️ Home GPU health check failed: {response.status_code}")
                self.home_gpu_available = False
                return False
                
        except requests.Timeout:
            logger.debug("⏱️ Home GPU health check timeout")
            self.home_gpu_available = False
            return False
        except Exception as e:
            logger.debug(f"❌ Home GPU health check failed: {e}")
            self.home_gpu_available = False
            return False
    
    def preprocess(self, image_data: str, num_nails: int, image_resolution: int) -> Tuple[Dict[str, Any], str]:
        """
        Preprocess image - tries Home GPU, falls back to RunPod
        
        Returns:
            Tuple of (result_dict, provider) where provider is "home" or "runpod"
        """
        self.stats["total_requests"] += 1
        
        # Try home GPU first
        if self.home_gpu_url and self.check_home_gpu_health():
            try:
                return self._preprocess_on_home(image_data, num_nails, image_resolution)
            except Exception as e:
                logger.warning(f"⚠️ Home GPU preprocessing failed, trying RunPod: {e}")
                self.home_gpu_available = False
        
        # Fall back to RunPod
        return self._preprocess_on_runpod(image_data, num_nails, image_resolution)
    
    def _preprocess_on_home(self, image_data: str, num_nails: int, image_resolution: int) -> Tuple[Dict[str, Any], str]:
        """Preprocess on home GPU (synchronous)"""
        self.stats["home_requests"] += 1
        logger.info("📤 Preprocessing on Home GPU")
        
        try:
            # Don't verify SSL for Tailscale Funnel
            verify_ssl = not self.home_gpu_url.endswith('.ts.net')
            
            response = requests.post(
                f"{self.home_gpu_url}/preprocess",
                json={
                    "imageData": image_data,
                    "num_nails": num_nails,
                    "image_resolution": image_resolution
                },
                timeout=30,
                verify=verify_ssl
            )
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"✅ Home GPU preprocessing complete")
                return result, "home"
            elif response.status_code == 503:
                raise Exception("Home GPU is busy")
            else:
                raise Exception(f"Home GPU error: {response.status_code}")
                
        except Exception as e:
            self.stats["home_failures"] += 1
            raise
    
    def _preprocess_on_runpod(self, image_data: str, num_nails: int, image_resolution: int) -> Tuple[Dict[str, Any], str]:
        """
        Preprocess on RunPod - returns job ID for polling
        Caller must poll for completion
        """
        self.stats["runpod_requests"] += 1
        logger.info("📤 Preprocessing on RunPod")
        
        headers = {
            "Authorization": f"Bearer {self.runpod_api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "input": {
                "endpoint": "preprocess",
                "imageData": image_data,
                "num_nails": num_nails,
                "image_resolution": image_resolution
            }
        }
        
        response = requests.post(
            self.runpod_run_url,
            headers=headers,
            json=payload,
            timeout=30
        )
        
        return response.json(), "runpod"
    
    def generate_stream(
        self, 
        image_data: str, 
        params: Dict[str, Any],
        on_event: Callable[[Dict[str, Any]], None]
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        """
        Generate string art with streaming - tries Home GPU, falls back to RunPod
        
        Args:
            image_data: Base64 encoded image
            params: Generation parameters
            on_event: Callback function called for each event (progress, new_line, etc.)
        
        Returns:
            Tuple of (final_result_dict, provider) where provider is "home" or "runpod"
        """
        self.stats["total_requests"] += 1
        
        # Try home GPU first (with streaming!)
        if self.home_gpu_url and self.check_home_gpu_health():
            try:
                return self._generate_stream_on_home(image_data, params, on_event)
            except Exception as e:
                logger.warning(f"⚠️ Home GPU streaming failed, trying RunPod: {e}")
                self.home_gpu_available = False
        
        # Fall back to RunPod (returns job ID for polling)
        return self._generate_on_runpod(image_data, params)
    
    def _generate_stream_on_home(
        self, 
        image_data: str, 
        params: Dict[str, Any],
        on_event: Callable[[Dict[str, Any]], None]
    ) -> Tuple[Dict[str, Any], str]:
        """
        Generate on home GPU with SSE streaming
        Calls on_event callback for each event received
        """
        self.stats["home_requests"] += 1
        logger.info("📤 Streaming generation from Home GPU")
        
        try:
            # Don't verify SSL for Tailscale Funnel
            verify_ssl = not self.home_gpu_url.endswith('.ts.net')
            
            response = requests.post(
                f"{self.home_gpu_url}/generate_stream",
                json={
                    "imageData": image_data,
                    "params": params
                },
                timeout=120,
                stream=True,  # Enable streaming
                verify=verify_ssl
            )
            
            if response.status_code != 200:
                if response.status_code == 503:
                    raise Exception("Home GPU is busy")
                else:
                    raise Exception(f"Home GPU error: {response.status_code}")
            
            # Process SSE stream
            final_result = None
            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue
                
                # SSE format: "data: {json}"
                if line.startswith("data: "):
                    try:
                        event_data = json.loads(line[6:])
                        event_type = event_data.get("type")
                        
                        # Call callback for each event
                        on_event(event_data)
                        
                        # Save final result
                        if event_type == "final_sequence":
                            final_result = event_data
                            
                    except json.JSONDecodeError as e:
                        logger.warning(f"Failed to parse SSE event: {e}")
            
            if final_result:
                logger.info(f"✅ Home GPU streaming complete")
                return final_result, "home"
            else:
                raise Exception("No final result received from stream")
                
        except Exception as e:
            self.stats["home_failures"] += 1
            raise
    
    def generate(self, image_data: str, params: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
        """
        DEPRECATED: Use generate_stream instead for real-time updates
        Legacy synchronous generation - tries Home GPU, falls back to RunPod
        
        Returns:
            Tuple of (result_dict, provider) where provider is "home" or "runpod"
        """
        self.stats["total_requests"] += 1
        
        # Try home GPU first
        if self.home_gpu_url and self.check_home_gpu_health():
            try:
                return self._generate_on_home_legacy(image_data, params)
            except Exception as e:
                logger.warning(f"⚠️ Home GPU generation failed, trying RunPod: {e}")
                self.home_gpu_available = False
        
        # Fall back to RunPod
        return self._generate_on_runpod(image_data, params)
    
    def _generate_on_home_legacy(self, image_data: str, params: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
        """Generate on home GPU (synchronous, legacy endpoint)"""
        self.stats["home_requests"] += 1
        logger.info("📤 Generating on Home GPU (legacy)")
        
        try:
            # Don't verify SSL for Tailscale Funnel
            verify_ssl = not self.home_gpu_url.endswith('.ts.net')
            
            response = requests.post(
                f"{self.home_gpu_url}/generate",
                json={
                    "imageData": image_data,
                    "params": params
                },
                timeout=120,
                verify=verify_ssl
            )
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"✅ Home GPU generation complete")
                return result, "home"
            elif response.status_code == 503:
                raise Exception("Home GPU is busy")
            else:
                raise Exception(f"Home GPU error: {response.status_code}")
                
        except Exception as e:
            self.stats["home_failures"] += 1
            raise
    
    def _generate_on_runpod(self, image_data: str, params: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
        """
        Generate on RunPod - returns job ID for polling
        Caller must poll for completion
        """
        self.stats["runpod_requests"] += 1
        logger.info("📤 Generating on RunPod")
        
        headers = {
            "Authorization": f"Bearer {self.runpod_api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "input": {
                "endpoint": "generate",
                "imageData": image_data,
                "params": params
            }
        }
        
        response = requests.post(
            self.runpod_run_url,
            headers=headers,
            json=payload,
            timeout=30
        )
        
        return response.json(), "runpod"
    
    def get_stats(self) -> Dict[str, Any]:
        """Get router statistics"""
        home_success_rate = 0
        if self.stats["home_requests"] > 0:
            home_success_rate = (
                (self.stats["home_requests"] - self.stats["home_failures"]) / 
                self.stats["home_requests"] * 100
            )
        
        runpod_success_rate = 0
        if self.stats["runpod_requests"] > 0:
            runpod_success_rate = (
                (self.stats["runpod_requests"] - self.stats["runpod_failures"]) / 
                self.stats["runpod_requests"] * 100
            )
        
        return {
            **self.stats,
            "home_gpu_available": self.home_gpu_available,
            "home_gpu_enabled": self.home_gpu_url is not None,
            "last_health_check": self.last_health_check.isoformat() if self.last_health_check else None,
            "home_success_rate": home_success_rate,
            "runpod_success_rate": runpod_success_rate
        }